# Back Up And Sync Files With Rsync

keywords: backup, back up, rsync, copy, sync, external drive, restore, checksum, verify, documents, pictures, archive

requires: rsync

when: the user wants files copied to an external drive, wants a backup made, or wants two folders kept the same

---

## Steps
1. Ask where the backup goes, if it is not already known - a path on an external drive under `/media/<you>/<label>/`, or a folder in the home directory. Do not pick a destination yourself.
2. Check the destination has room: run_command `df -h /media/<you>/<label>` and compare the `Avail` column with what run_command `du -sh ~/Documents` reports for the source. A backup that does not fit is not a backup.
3. Confirm the destination exists and note what is already in it: run_command `ls -la /media/<you>/<label>`. If the target folder inside it does not exist yet, it is created in step 6, not now.
4. Do the dry run: run_command `rsync -av --dry-run ~/Documents/ /media/<you>/<label>/astraos-backup/Documents/`. The trailing slash on the source means "the contents of this folder"; without it rsync would copy the folder itself into the destination, one level deeper than the user asked for.
5. Read the dry run. `--dry-run` changes nothing: it prints every file that would be copied, every directory that would be created, and a final line giving the total size. Report that list and that total.
6. Create the destination folder once, only if the dry run said it would be created: run_command `mkdir -p /media/<you>/<label>/astraos-backup/Documents`.
7. Stop and let the user decide. Print the dry run's full list, then SHOW THE LIST AND WAIT FOR CONFIRMATION. The user has to say yes to that list before a single byte is copied. A hesitating answer, or no answer, is a no.
8. Only after a yes, run the real copy, the same command with `--dry-run` removed: run_command `rsync -av ~/Documents/ /media/<you>/<label>/astraos-backup/Documents/`. One rsync per directory - repeat for `~/Pictures/` and `~/.config/` as separate commands, so each output stays readable and each can be checked.
9. Verify the copy: run_command `rsync -av --checksum --dry-run ~/Documents/ /media/<you>/<label>/astraos-backup/Documents/`. `--checksum` compares file contents instead of timestamps. If this second pass prints no file names, the destination matches the source exactly. Report that, and report anything it lists.
10. If the user asked to make the destination match the source exactly - deleting files in the destination that no longer exist in the source - run the dry run with `--delete` added first, print what it would remove, and SHOW THE LIST AND WAIT FOR CONFIRMATION before running the real thing. A `--delete` nobody was shown is data loss with no witnesses.

## Notes

`-a` is archive: it preserves times, permissions, symlinks and recursion, which is what "the same files" means. `-v` is verbose, and it is what makes the dry run's output the list you show. `--dry-run` is the whole safety model of this skill - rsync is fast and destructive at the same time, so the plan always runs first and the copy never runs unannounced.

The source is never modified. Rsync reads `~/Documents`, `~/Pictures` and `~/.config` and writes only to the destination. `--delete` is the one flag that changes that relationship, because it acts on the destination; that is exactly why it needs its own confirmation with its own list.

`~/.config` is a hidden directory and holds the desktop settings - keyboard shortcuts, panel layout, the assistant's settings. Include it when the user asked for a full backup, but never `--delete` a `.config` backup without the list, because the destination may be a machine whose desktop is configured differently.

Nothing here deletes a source file, truncates a source file, or writes outside the destination. If a step looks like it rewrites something in `~`, it is wrong - re-read step 4.
