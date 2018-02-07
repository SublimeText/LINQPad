import collections
import functools
import html
import os
import re
import subprocess
import sys
import threading
import time
import codecs

import sublime
import sublime_plugin

# Code in this file is a modified version of the Default/exec.py in devlopment
# build 3156.

class ProcessListener(object):
    def on_data(self, proc, data):
        pass

    def on_finished(self, proc):
        pass


class AsyncProcess(object):
    """
    Encapsulates subprocess.Popen, forwarding stdout to a supplied
    ProcessListener (on a separate thread)
    """
    def __init__(self, cmd, shell_cmd, env, listener, working_dir="",
                 file_regex="", path="", shell=False):
        """ "path" and "shell" are options in build systems """

        if not shell_cmd and not cmd:
            raise ValueError("shell_cmd or cmd is required")

        if shell_cmd and not isinstance(shell_cmd, str):
            raise ValueError("shell_cmd must be a string")

        self.listener = listener
        self.killed = False

        self.stderr_buffer = ""
        self.working_dir = working_dir

        # Only store the file_regex if one was provided, so we don't try to
        # rewrite lines if we're not told how to recognize them.
        self.file_regex = re.compile(file_regex, flags=re.MULTILINE) if file_regex else None

        self.start_time = time.time()

        # Hide the console window on Windows
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        # Set temporary PATH to locate executable in cmd
        if path:
            old_path = os.environ["PATH"]
            # The user decides in the build system whether he wants to append $PATH
            # or tuck it at the front: "$PATH;C:\\new\\path", "C:\\new\\path;$PATH"
            os.environ["PATH"] = os.path.expandvars(path)

        proc_env = os.environ.copy()
        proc_env.update(env)
        for k, v in proc_env.items():
            proc_env[k] = os.path.expandvars(v)

        if shell_cmd and sys.platform == "win32":
            # Use shell=True on Windows, so shell_cmd is passed through with the correct escaping
            self.proc = subprocess.Popen(
                shell_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                startupinfo=startupinfo,
                env=proc_env,
                shell=True)
        elif shell_cmd and sys.platform == "darwin":
            # Use a login shell on OSX, otherwise the users expected env vars won't be setup
            self.proc = subprocess.Popen(
                ["/usr/bin/env", "bash", "-l", "-c", shell_cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                startupinfo=startupinfo,
                env=proc_env,
                shell=False)
        elif shell_cmd and sys.platform == "linux":
            # Explicitly use /bin/bash on Linux, to keep Linux and OSX as
            # similar as possible. A login shell is explicitly not used for
            # linux, as it's not required
            self.proc = subprocess.Popen(
                ["/usr/bin/env", "bash", "-c", shell_cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                startupinfo=startupinfo,
                env=proc_env,
                shell=False)
        else:
            # Old style build system, just do what it asks
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                startupinfo=startupinfo,
                env=proc_env,
                shell=shell)

        if path:
            os.environ["PATH"] = old_path

        if self.proc.stdout:
            threading.Thread(
                target=self.read_fileno,
                args=(self.proc.stdout.fileno(), False)
            ).start()

        if self.proc.stderr:
            threading.Thread(
                target=self.read_fileno,
                args=(self.proc.stderr.fileno(), True)
            ).start()

    def kill(self):
        if not self.killed:
            self.killed = True
            if sys.platform == "win32":
                # terminate would not kill process opened by the shell cmd.exe,
                # it will only kill cmd.exe leaving the child running
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                subprocess.Popen(
                    "taskkill /PID " + str(self.proc.pid),
                    startupinfo=startupinfo)
            else:
                self.proc.terminate()
            self.listener = None

    def poll(self):
        return self.proc.poll() is None

    def exit_code(self):
        return self.proc.poll()

    def read_fileno(self, fileno, is_stderr):
        decoder_cls = codecs.getincrementaldecoder(self.listener.encoding)
        decoder = decoder_cls('replace')
        while True:
            # Get the data and mormalize newlines, Sublime Text always uses a
            # single \n separator in memory.
            data = decoder.decode(os.read(fileno, 2**16))
            data = data.replace('\r\n', '\n').replace('\r', '\n')

            if len(data) > 0:
                if self.listener:
                    # For stderr, accumulate data into our buffer and then let
                    # full lines through.
                    if is_stderr:
                        self.stderr_buffer += data
                        nPos = self.stderr_buffer.rfind("\n")
                        if nPos >= 0:
                            self.listener.on_data(self, self.stderr_buffer[:nPos+1])
                            self.stderr_buffer = self.stderr_buffer[nPos+1:]

                    else:
                        self.listener.on_data(self, data)
            else:
                os.close(fileno)
                if self.listener:
                    # For std_err, see if we need to send any buffered and
                    # unterminated output
                    if is_stderr:
                        if self.stderr_buffer:
                            self.listener.on_data(self, self.stderr_buffer)
                            self.stderr_buffer = ""
                    else:
                        # Only trigger on_finished for stdout
                        self.listener.on_finished(self)

                break


class LinqpadExecCommand(sublime_plugin.WindowCommand, ProcessListener):
    BLOCK_SIZE = 2**14
    text_queue = collections.deque()
    text_buffer = ""
    is_finished = False
    file_regex = None
    text_queue_proc = None
    text_queue_lock = threading.Lock()

    proc = None

    errs_by_file = {}
    phantom_sets_by_buffer = {}
    show_errors_inline = True

    _hdr_start = re.compile(r'^<\s*query', flags=re.IGNORECASE)
    _hdr_end = re.compile(r'</query\s*>', flags=re.IGNORECASE)

    def run(
            self,
            cmd=None,
            shell_cmd=None,
            file_regex="",
            line_regex="",
            working_dir="",
            encoding="utf-8",
            env={},
            quiet=False,
            kill=False,
            update_phantoms_only=False,
            hide_phantoms_only=False,
            word_wrap=True,
            syntax="Packages/Text/Plain text.tmLanguage",
            # Catches "path" and "shell"
            **kwargs):

        if update_phantoms_only:
            if self.show_errors_inline:
                self.update_phantoms()
            return
        if hide_phantoms_only:
            self.hide_phantoms()
            return

        # In theory, starting at build 3124 the sublime-build file is allowed
        # to have this key to provide either a command to execute or arguments
        # to the standard target to kill it.
        #
        # At least in build 3143, Sublime doesn't remove this argument from the
        # target before it invokes it in the build, which makes the underlying
        # AsyncProcess instance angry.
        #
        # As an expedient fix, if that argument is present, throw it away at
        # this point so that it doesn't pass through.
        #
        # Need to investigate this further to see why this might be happening.
        if "cancel" in kwargs:
            kwargs.pop("cancel")

        # clear the text_queue
        with self.text_queue_lock:
            self.text_queue.clear()
            self.text_queue_proc = None
            self.text_buffer = ""
            self.is_finished = False

        if kill:
            if self.proc:
                self.proc.kill()
                self.proc = None
                self.append_string(None, "[Cancelled]")
            return

        if not hasattr(self, 'output_view'):
            # Try not to call get_output_panel until the regexes are assigned
            self.output_view = self.window.create_output_panel("exec")

        # Default the to the current files directory if no working directory was given
        if working_dir == "" and self.window.active_view() and self.window.active_view().file_name():
            working_dir = os.path.dirname(self.window.active_view().file_name())

        # Save the incoming regex so that we can use it to rewrite errors lines
        # before they get to the buffer.
        self.file_regex = re.compile(file_regex, flags=re.MULTILINE)

        # Capture the offset into the file that error messages will relate to,
        # since lprun doesn't take the potential XML header on the file into
        # account.
        #
        # TODO: This always assumes the current file; it needs to instead try
        # to get the file from the command about to be executed.
        if self.window.active_view() and self.window.active_view().file_name():
            try:
                self.script_offset = self.get_script_offset(self.window.active_view().file_name())
            except Exception as err:
                print("linqpad_exec cannot determine script error offset")
                print(err)
                self.script_offset = 0
        else:
            print("linqpad_exec cannot determine script error offset")


        self.output_view.settings().set("result_file_regex", file_regex)
        self.output_view.settings().set("result_line_regex", line_regex)
        self.output_view.settings().set("result_base_dir", working_dir)
        self.output_view.settings().set("word_wrap", word_wrap)
        self.output_view.settings().set("line_numbers", False)
        self.output_view.settings().set("gutter", False)
        self.output_view.settings().set("scroll_past_end", False)
        self.output_view.assign_syntax(syntax)

        # Call create_output_panel a second time after assigning the above
        # settings, so that it'll be picked up as a result buffer
        self.window.create_output_panel("exec")

        self.encoding = encoding
        self.quiet = quiet

        self.proc = None
        if not self.quiet:
            if shell_cmd:
                print("Running " + shell_cmd)
            elif cmd:
                cmd_string = cmd
                if not isinstance(cmd, str):
                    cmd_string = " ".join(cmd)
                print("Running " + cmd_string)
            sublime.status_message("Building")

        show_panel_on_build = sublime.load_settings("Preferences.sublime-settings").get("show_panel_on_build", True)
        if show_panel_on_build:
            self.window.run_command("show_panel", {"panel": "output.exec"})

        self.hide_phantoms()
        self.show_errors_inline = sublime.load_settings("Preferences.sublime-settings").get("show_errors_inline", True)

        merged_env = env.copy()
        if self.window.active_view():
            user_env = self.window.active_view().settings().get('build_env')
            if user_env:
                merged_env.update(user_env)

        # Change to the working dir, rather than spawning the process with it,
        # so that emitted working dir relative path names make sense
        if working_dir != "":
            os.chdir(working_dir)

        self.debug_text = ""
        if shell_cmd:
            self.debug_text += "[shell_cmd: " + shell_cmd + "]\n"
        else:
            self.debug_text += "[cmd: " + str(cmd) + "]\n"
        self.debug_text += "[dir: " + str(os.getcwd()) + "]\n"
        if "PATH" in merged_env:
            self.debug_text += "[path: " + str(merged_env["PATH"]) + "]"
        else:
            self.debug_text += "[path: " + str(os.environ["PATH"]) + "]"

        try:
            # Forward kwargs to AsyncProcess
            self.proc = AsyncProcess(cmd, shell_cmd, merged_env, self,
                working_dir, file_regex, **kwargs)

            with self.text_queue_lock:
                self.text_queue_proc = self.proc

        except Exception as e:
            self.append_string(None, str(e) + "\n")
            self.append_string(None, self.debug_text + "\n")
            if not self.quiet:
                self.append_string(None, "[Finished]")

    def get_script_offset(self, script_file):
        """
        LINQPad scripts may optionally start with a <Query></Query> tag pair to
        provide configuration information to the processor. When a script has
        such a header, the error messages that lprun reports are relative to
        the first non-blank line after the header.

        This method examines the script file in order to determine what offset
        to add to the reported line numbers from lprun in order to correctly
        identify the source line.
        """
        # True/False indates the file has a header, None if we don't know yet.
        header = None
        in_header = False
        offset = 0

        with open(script_file, 'r') as file:
            for line in file:
                # Don't do any special processing on blank lines.
                line = line.lstrip()
                if line:
                    # See if this line starts a header; can only happen if we
                    # have not already seen a header start in this file.
                    if header is None and self._hdr_start.search(line):
                        header = in_header = True

                    # See if the header ends on this line; can only happen
                    # while we are inside a header, and can happen on the same
                    # line that started the header.
                    if header and in_header and self._hdr_end.search(line):
                        in_header=False

                    # Every other line is either a header line or a script
                    # line, depending on the state of the header flag.
                    #
                    # NOTE: This cannot happen on the same line that ended the
                    # header because lprun ignores code trailing on the same
                    # line as the header close tag.
                    elif not in_header:
                        # We found code before a header; script has no header.
                        if header is None:
                            return 0

                        # This is the first code line after the header closed.
                        return offset

                offset += 1

        # If we found and closed a header, the script starts at the last seen.
        # offset. Otherwise, no no header was found, the header wasn't closed,
        # or was all header and no body.
        return offset if header == False else 0

    def is_enabled(self, kill=False, **kwargs):
        if kill:
            return (self.proc is not None) and self.proc.poll()
        else:
            return True

    def append_string(self, proc, str):
        was_empty = False
        with self.text_queue_lock:
            if proc != self.text_queue_proc and proc:
                # a second call to exec has been made before the first one
                # finished, ignore it instead of intermingling the output.
                proc.kill()
                return

            if len(self.text_queue) == 0:
                was_empty = True
                self.text_queue.append("")

            available = self.BLOCK_SIZE - len(self.text_queue[-1])

            if len(str) < available:
                cur = self.text_queue.pop()
                self.text_queue.append(cur + str)
            else:
                self.text_queue.append(str)

        if was_empty:
            sublime.set_timeout(self.service_text_queue, 0)

    def service_text_queue(self):
        is_empty = False
        with self.text_queue_lock:
            if len(self.text_queue) == 0:
                # this can happen if a new build was started, which will clear
                # the text_queue
                return

            characters = self.text_queue.popleft()
            is_empty = (len(self.text_queue) == 0)

        # Accumulate the incoming characters, and then see if we need to send
        # something to the panel yet; this happens when there is at least one
        # full line in our buffer or the command has finished executing.
        self.text_buffer += characters
        nPos = characters.rfind('\n')
        if nPos >= 0 or self.is_finished:
            def replacer(match):
                # Get the line from this message and adjust it.
                adj_line = str(int(match.group(2)) + self.script_offset)

                # Get this message out and replace the number with the new one.
                msg = match.group(0)
                sPos = match.start(2) - match.start(0)
                ePos = match.end(2) - match.start(0)

                return msg[:sPos] + adj_line + msg[ePos:]

            # Do potential command rewriting
            self.text_buffer = re.sub(self.file_regex, replacer,
                                      self.text_buffer)

            # If we're not finished with the output, then only write complete
            # lines out to the view. In that case the trailing line will be
            # left in our buffer after we're done so for the next read to
            # complete.
            unterminated_remainder = ""
            if not self.is_finished:
                # nPos is the index of the newline; include it in the slice.
                unterminated_remainder = self.text_buffer[nPos + 1:]
                self.text_buffer = self.text_buffer[:nPos + 1]

            self.output_view.run_command(
                'append',
                {'characters': self.text_buffer, 'force': True, 'scroll_to_end': True})

            # Save what might have been left.
            self.text_buffer = unterminated_remainder

            if self.show_errors_inline:
                errs = self.output_view.find_all_results_with_text()
                errs_by_file = {}
                for file, line, column, text in errs:
                    if file not in errs_by_file:
                        errs_by_file[file] = []
                    errs_by_file[file].append((line, column, text))
                self.errs_by_file = errs_by_file

                self.update_phantoms()

        if not is_empty:
            sublime.set_timeout(self.service_text_queue, 1)

    def finish(self, proc):
        # Flag that we're finished so that the handler knows to flush the rest
        # of the buffered output.
        self.is_finished=True
        if not self.quiet:
            elapsed = time.time() - proc.start_time
            exit_code = proc.exit_code()
            if exit_code == 0 or exit_code is None:
                self.append_string(proc, "[Finished in %.1fs]" % elapsed)
            else:
                self.append_string(proc, "[Finished in %.1fs with exit code %d]\n" % (elapsed, exit_code))
                self.append_string(proc, self.debug_text)

        if proc != self.proc:
            return

        errs = self.output_view.find_all_results()
        if len(errs) == 0:
            sublime.status_message("Build finished")
        else:
            sublime.status_message("Build finished with %d errors" % len(errs))

    def on_data(self, proc, data):
        self.append_string(proc, data)

    def on_finished(self, proc):
        sublime.set_timeout(functools.partial(self.finish, proc), 0)

    def update_phantoms(self):
        stylesheet = '''
            <style>
                div.error-arrow {
                    border-top: 0.4rem solid transparent;
                    border-left: 0.5rem solid color(var(--redish) blend(var(--background) 30%));
                    width: 0;
                    height: 0;
                }
                div.error {
                    padding: 0.4rem 0 0.4rem 0.7rem;
                    margin: 0 0 0.2rem;
                    border-radius: 0 0.2rem 0.2rem 0.2rem;
                }

                div.error span.message {
                    padding-right: 0.7rem;
                }

                div.error a {
                    text-decoration: inherit;
                    padding: 0.35rem 0.7rem 0.45rem 0.8rem;
                    position: relative;
                    bottom: 0.05rem;
                    border-radius: 0 0.2rem 0.2rem 0;
                    font-weight: bold;
                }
                html.dark div.error a {
                    background-color: #00000018;
                }
                html.light div.error a {
                    background-color: #ffffff18;
                }
            </style>
        '''

        for file, errs in self.errs_by_file.items():
            view = self.window.find_open_file(file)
            if view:

                buffer_id = view.buffer_id()
                if buffer_id not in self.phantom_sets_by_buffer:
                    phantom_set = sublime.PhantomSet(view, "exec")
                    self.phantom_sets_by_buffer[buffer_id] = phantom_set
                else:
                    phantom_set = self.phantom_sets_by_buffer[buffer_id]

                phantoms = []

                for line, column, text in errs:
                    pt = view.text_point(line - 1, column - 1)
                    phantoms.append(sublime.Phantom(
                        sublime.Region(pt, view.line(pt).b),
                        ('<body id=inline-error>' + stylesheet +
                            '<div class="error-arrow"></div><div class="error">' +
                            '<span class="message">' + html.escape(text, quote=False) + '</span>' +
                            '<a href=hide>' + chr(0x00D7) + '</a></div>' +
                            '</body>'),
                        sublime.LAYOUT_BELOW,
                        on_navigate=self.on_phantom_navigate))

                phantom_set.update(phantoms)

    def hide_phantoms(self):
        for file, errs in self.errs_by_file.items():
            view = self.window.find_open_file(file)
            if view:
                view.erase_phantoms("exec")

        self.errs_by_file = {}
        self.phantom_sets_by_buffer = {}
        self.show_errors_inline = False

    def on_phantom_navigate(self, url):
        self.hide_phantoms()


class LinqpadExecEventListener(sublime_plugin.EventListener):
    def on_load(self, view):
        w = view.window()
        if w is not None:
            w.run_command('linqpad_exec', {'update_phantoms_only': True})
