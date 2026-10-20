# Summarise A Folder Of Documents

keywords: summarise, summarize, summary, brief, folder, documents, txt, md, csv, pdf, report, digest, sources, cite

requires: pdftotext

when: the user wants a short brief out of a folder of text documents, or wants to know what a set of files is about

---

## Steps
1. List the folder first: `search_files` with part of the name, or `read_file` on a folder listing only if the user gave the folder. Read the whole listing before reading any file, so the brief is about what is actually there and not about the two files you happened to open.
2. Sort the files into kinds by extension: `.txt` and `.md` are readable with `read_file`; `.csv` needs the header line read first; `.pdf` needs `read_pdf`; anything else - `.docx`, `.xlsx`, images, archives - is not text and needs a conversion step from the pdf-office skill before it can be summarised.
3. Read a plain text file: `read_file` with the path. It returns the whole file, refuses a binary, and refuses anything over 1 MB; for a long file ask for a narrower question rather than inventing the middle.
4. Read a CSV's shape before its rows: `read_file` returns the header and the first records, which is enough to say what the columns are. Never quote a number from a CSV you have not read a row of.
5. Extract a PDF: `read_pdf` with the path. If it comes back with no text layer, say that in the brief under a "could not read" line and move on. Do not guess what a scanned PDF says from its name.
6. When asked to compare two files, use `compare_files`; it returns a unified diff, and an identical pair says so rather than producing an empty answer that reads like a failure.
7. Write the brief with `write_file` only when the user asked for a file; it writes inside the assistant's workspace, not into the user's Documents. One short paragraph per document, in the order the user gave or alphabetically, and at the end of every claim put the file it came from, for example `(~/Documents/notes.md)`. A sentence that cannot be traced to a file does not go in the brief.
8. Before saving or presenting the brief, run `verify_citations` with the brief and the paths you read. Fix every citation it reports as unresolved, or remove the sentence; a failed check is not a footnote to ignore.
9. Add a section headed "What is missing". Name the questions this folder does not answer, and name the file or the source that would answer them - a project with no budget file, a log with no error report, a date range that starts after the event.
10. Finish with the totals: how many files were in the folder, how many were read, how many could not be read and why. If the user asked for a file, print the path `write_file` returned.

## Notes

The citation rule is the whole point of this skill. Every sentence in the brief must be attributable to one file path that was actually read. A model that summarises a folder it did not open produces fluent fiction with file names in it, and the user has no way to catch it - so: if a file was not read, it is not summarised, and it is named in the "could not read" lines instead.

There is no step here that writes to, renames or moves any source document. `read_file`, `read_pdf`, `compare_files` and `verify_citations` are read-only by construction; `write_file` writes only inside the assistant's own workspace. A brief is also allowed to be short: three documents summarised honestly beats twelve paraphrased from their file names.

If the folder is large, say so and ask the user which files matter before reading all of them; reading everything is the safe default only when the folder is small enough that every file really was opened. Numbers must be copied, never rounded, inferred or estimated - and a figure that appears in two files with different values is a contradiction to report, not one to average.
