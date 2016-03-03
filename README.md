# LINQPad
Syntax highlighting and build system for LINQPad (`.linq`) scripts.

## Build System

If you have LINQPad installed (i.e. you are on Windows), and `lprun` is available on your path, you can use the Sublime Text build system to execute your linq script using [`lprun`](https://www.linqpad.net/lprun.aspx), and the output will appear in the build results panel.

There are 3 build variants:

- `lprun` - which will output results in text mode. Lists and non-basic objects are formatted as JSON.
- `Output CSV` - which will render simple lists in Excel-friendly CSV.
- `Compile Only` - which will check your script for errors/warnings only and not execute any code.

## Installation

The recommended way to install the LINQPad syntax highlighting and build system for Sublime Text is via [Package Control](https://packagecontrol.io/packages/LinqPad). Package Control will install the plugin on your system and keep it up to date.

1. [Ensure Package Control is installed.](https://packagecontrol.io/installation)
1. In Sublime Text, open the `Preferences` menu, and select `Package Control`.
1. Select `Package Control: Install Package`.
1. Start typing `LinqPad`. When you see it, select it.
1. Wait for it to install.
1. Re-open any open linq files, or set their syntax to linq manually.
1. Enjoy!
