# SYNTAX TEST "linq.sublime-syntax"
<Query Kind="Nonsense">
#            ^^^^^^^^ source.linqpad text.xml meta.tag.xml string.quoted.double.xml invalid.illegal.unrecognized.querykind.linq
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

# <- source.linqpad - text.xml
// comment
# <- source.linqpad invalid.illegal.unknown_syntax.linq
