# Triage Local Email Offline

keywords: email, mail, maildir, mbox, triage, inbox, reply, draft, offline, notmuch, message, unread, message headers

requires: grep

when: the user has local mail in a Maildir or an mbox file and wants it sorted, read, or a reply drafted

---

## Steps
1. Find the mail store. Ask the user if you do not know it. The usual places are `~/Maildir`, `~/.local/share/mail`, and a single `~/mail/archive.mbox` file.
2. Count what is there: run_command `ls ~/Maildir/new` for unseen messages and run_command `ls ~/Maildir/cur` for the rest. Note that a Maildir message is one file per message, named with a timestamp and flags.
3. For an mbox file, count the messages with run_command `grep -c "^From " ~/mail/archive.mbox`. In an mbox every message starts with a line beginning `From ` followed by a space, and that count is the number of messages.
4. If notmuch is installed, use it instead and it is faster: run_command `notmuch new` to build notmuch's own index (it writes only that index, never a message), then run_command `notmuch search tag:inbox` for the list, then run_command `notmuch show --format=text <id>` for one message's headers and body. The last two are read-only.
5. Read one message at a time: run_command `cat ~/Maildir/new/<file>`. Read the From, To, Subject and Date headers first, then the body. Do not read a message you have already read - each command costs a turn.
6. Classify every message into exactly one of three groups: needs reply, needs reading, or can be ignored. Give the reason for each, in a phrase that names the file, for example `needs reply - asks for the invoice number (Maildir/new/1750000000.M1P123.host)`.
7. Print the three groups with their counts, the newest first. A message that goes in "can be ignored" still gets named - the user checks a classification by seeing what was in it.
8. Draft the replies. Write each draft in the answer as plain text, with its own To, Subject and body, ready for the user to copy. Address it to the From header of the message it answers and keep the Subject as `Re: <original subject>`.
9. Stop there. The drafts are printed for a human to read and send. Nothing is sent, marked as read, moved, filed or deleted, and no step exists that would do any of that.

## Notes

The assistant cannot send email. There is no send action in the action catalog, no mail transport agent is configured by this distribution, and a step that says "send", "reply", "file" or "mark as read" as an instruction to the machine is wrong - those words only ever describe what the *draft* is for. The user sends from their own mail program with their own account.

This is an offline skill by definition: it reads files under the user's home directory and makes no network request of any kind. Do not open a browser, do not call `search_web`, and do not offer to "check the mailbox online".

Reading is the safe part, so be liberal with it. `grep` and `cat` on a mail file cannot change it. If a message is base64 or quoted-printable encoded, say so rather than printing the encoded block as if it were the text; `grep -c "^From "` remains the reliable count either way.
