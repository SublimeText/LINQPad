# SYNTAX TEST "linq.sublime-syntax"
<Query Kind="Expression">
#            ^^^^^^^^^^ source.linqpad text.xml meta.tag.xml string.quoted.double.xml - invalid.illegal.unrecognized.querykind.linq
  <Connection>
#  ^^^^^^^^^^ source.linqpad text.xml meta.tag.xml entity.name.tag.localname.xml
    <ID>60154894-9165-4f77-b527-0bc717db8966</ID>
    <Persist>true</Persist>
    <Server>(localdb)\MSSQLLocalDB</Server>
    <NoPluralization>true</NoPluralization>
    <NoCapitalization>true</NoCapitalization>
    <Database>master</Database>
    <ShowServer>true</ShowServer>
  </Connection>
</Query>
#^^^^^^^^ source.linqpad text.xml - source.cs

# <- source.linqpad source.cs - text.xml
// comment
# <- source.linqpad source.cs comment.line.double-slash.cs punctuation.definition.comment.cs
var test = "Test".IndexOf("e") + 1;
#           ^ source.linqpad source.cs string.quoted.double.cs
#                            ^ source.linqpad source.cs punctuation.section.group.end.cs
#                                ^ source.linqpad source.cs constant.numeric.cs
test.Dump();
#   ^ source.cs punctuation.accessor.dot.cs
#          ^ source.cs punctuation.terminator.statement.cs
