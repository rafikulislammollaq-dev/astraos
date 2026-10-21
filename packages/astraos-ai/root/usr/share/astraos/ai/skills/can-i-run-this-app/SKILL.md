# Can I run this app on AstraOS?

keywords: windows app, can i run, does it work, compatibility, run on linux, excel, word, photoshop, teams, zoom, spotify, netflix, discord, autocad, minecraft, application, program, software
requires: apt-cache
when: the user names an application they know from another system - usually Windows, sometimes macOS, Android or a game - and asks whether AstraOS can run it, replace it, or what the honest options are

---

## Steps

1. Say what kind of thing it is before you say whether it works: a document, a
   photo, a game, a chat application, a line-of-business tool. The answer depends
   on the kind, and the user usually cares about the kind more than the name.
2. Read the table: open_file on
   /usr/share/astraos/ai/knowledge/windows-applications-on-astraos.md. It names the
   native answer, the Wine answer and the browser answer for the applications
   people actually ask about.
3. If the application is not in the table, check the archive: run_command
   `apt-cache policy <name>` and run_command `apt-cache search <name>`. A
   candidate version in the archive means native, and the package name is what
   the user installs.
4. If the archive has nothing, check the second road: Wine is in this image, so
   run_command `apt-cache policy wine` confirms it, and an application that is not
   in the archive can often be installed with `wine <setup.exe>`. Say "often", not
   "will": Wine runs a great many applications and a few of them badly.
5. If neither works, check the third road: the browser. The vendor's own site is
   usually where the application works, and it is the vendor's page, not a native
   program. Say that distinction plainly.
6. If nothing works, say so. "This one does not run on AstraOS" is a complete and
   useful answer when it is true. Do not offer a hope, and do not invent a
   substitute that is not in the table.
7. Give the detail, not only the verdict: what the closest native program is,
   whether the file format is compatible, what happens to the account and the
   licence, and what the user gives up by switching. The table's last column
   usually says this - use it.
8. Offer the next step in one line. The assistant cannot install anything, so
   print the command and let the user run it: `sudo apt install <package>`. For a
   web answer, say which site.
9. If the user's files matter more than the application - "I have a folder of
   .xlsx files and no Word" - answer that first: the formats usually open
   natively, and that is the answer they needed.

## Notes

Every command here is read-only. `apt-cache policy` and `apt-cache search` read
the index; nothing is installed, and the assistant does not run `sudo` - it
refuses it before the command is executed, which is correct behaviour and not a
bug.

The four verdicts are native, Wine, browser and no. They are the ones the table
uses, and a verdict outside them ("probably", "it should work") is not an answer
the user can act on.
