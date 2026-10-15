# Find And Organise Files

keywords: find, files, search, locate, organise, organize, tidy, move, disk, downloads, clean up, extension, old files, large files

requires: find

when: the user cannot find a file, wants a folder tidied, or wants files moved somewhere else

---

## Steps

1. Search by name, case-insensitively: run_command `find ~/Documents -iname "*report*" -type f`. `-iname` matches either case; `-type f` keeps it to files and skips directories.
2. Search by extension: run_command `find ~/Downloads -type f -name "*.pdf"`. One extension per command.
3. Search by age: run_command `find ~/Downloads -type f -mtime +30` finds files last modified more than 30 days ago. Change the number, not the flag.
4. Search by size: run_command `find ~/Downloads -type f -size +100M` finds files over 100 megabytes. `+100M` means "more than"; without the leading `+` it means exactly that size and finds nothing useful.
5. Inspect what you found, one command at a time: `ls -la ~/Downloads/<file>` for the size, the date and the permissions; `du -sh ~/Downloads` for how much space the whole folder takes; `file ~/Downloads/<file>` for what the file actually is, which is how you tell a PDF renamed to .txt.
6. Build the plan in words before touching anything. For every file, print one line of the form `~/Downloads/old-thing.pdf -> ~/Documents/reports/`. Finish with the count of files and the total size, from `du -sh`.
7. Show the plan and stop. Print the complete list in the answer, exactly as it will be executed, then SHOW THE LIST AND WAIT FOR CONFIRMATION. The user has to say yes to that list. Silence, a change of subject, or "probably fine" is not a yes.
8. Only after the user confirms: run_command `mkdir -p ~/Documents/reports` once, if the destination folder does not exist yet.
9. Then move, one directory at a time so the output stays readable: run_command `mv ~/Downloads/old-thing.pdf ~/Documents/reports/`. `mv` keeps the file's contents and timestamps and removes it from where it was, so a move is also the last moment it is easy to undo. Only a list the user has already said yes to may be moved - SHOW THE LIST AND WAIT FOR CONFIRMATION for any list that was not printed and agreed, including a single file.
10. Verify the move: run_command `ls -la ~/Documents/reports/` and confirm every file on the list arrived. Report anything that did not.

## Notes

The list is the safety mechanism, and printing it is a real step rather than a courtesy. A user who is shown ten files and asks you to move them has told you what they wanted; a user shown "moved your downloads" afterwards has not been told anything they can check.

Never use `find -delete`. It removes files as it walks, it has no undo, and its `-name` pattern matches far more than people expect - an empty quotes result deletes nothing and a stray dot deletes the folder. Never use `find -exec mv` either: it moves files the moment it finds them, in whatever order the filesystem returns them, and the list never reaches the user's eyes before the damage. If a step appears to delete or move anything, it must first print the list and get a yes.

`mv` is the only move action available. There is no copy-and-delete trick worth doing: `mv` within one filesystem is a rename and does not rewrite the data, so it is both faster and safer than copying and removing the original.

One `find` command may only ever contain a search and an action that prints. Flags such as `-print`, `-mtime` and `-size` are fine. `-delete`, `-exec`, `-execdir`, `-ok` and `-fprint` are not, and this assistant's command runner refuses a `;` anyway, which most `-exec` forms need.
