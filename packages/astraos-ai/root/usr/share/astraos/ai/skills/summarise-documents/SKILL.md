# Summarise A Folder Of Documents

keywords: summarise, summarize, summary, brief, folder, documents, txt, md, csv, pdf, report, digest, sources, cite

requires: pdftotext

when: the user wants a short brief out of a folder of text documents, or wants to know what a set of files is about

---

## Steps
1. List the folder first: run_command `ls -la ~/Documents/`. Read the whole listing before reading any file, so the brief is about what is actually there and not about the two files you happened to open.
2. Sort the files into kinds by extension: `.txt` and `.md` are readable as they are; `.csv` needs the header line read first; `.pdf` needs extracting; anything else - `.docx`, `.xlsx`, images, archives - is not text and needs a conversion step from the pdf-office skill before it can be summarised.
3. Read a plain text file: run_command `cat ~/Documents/notes.md`. `cat` prints the whole file and writes nothing. For a long file, read `head -n 100 ~/Documents/notes.md` for the opening and `tail -n 40` for the closing.
4. Read a CSV's shape before its rows: run_command `head -n 5 ~/Documents/data.csv` gives the header row and the first records, which is enough to say what the columns are. Never quote a number from a CSV you have not read a row of.
5. Extract a PDF: run_command `pdftotext -layout ~/Documents/report.pdf -`. If it comes back empty, the PDF has no text layer; say that in the brief under a "could not read" line and move on. Do not guess what a scanned PDF says from its name.
6. Write the brief. One short paragraph per document, in the order the user gave or alphabetically, and at the end of every claim put the file it came from, for example `(~/Documents/notes.md)`. A sentence that cannot be traced to a file does not go in the brief.
7. Add a section headed "What is missing". Name the questions this folder does not answer, and name the file or the source that would answer them - a project with no budget file, a log with no error report, a date range that starts after the event.
8. Finish with the totals: how many files were in the folder, how many were read, how many could not be read and why. Do not write the brief to a file unless the user asked for one, and if they did, print the path of the file you wrote.

## Notes

The citation rule is the whole point of this skill. Every sentence in the brief must be attributable to one file path that was actually read. A model that summarises a folder it did not open produces fluent fiction with file names in it, and the user has no way to catch it - so: if a file was not read, it is not summarised, and it is named in the "could not read" lines instead.

There is no step here that writes to, renames or moves any source document. `cat`, `head`, `tail` and `pdftotext -` are read-only by construction. A brief is also allowed to be short: three documents summarised honestly beats twelve paraphrased from their file names.

If the folder is large, say so and ask the user which files matter before reading all of them; reading everything is the safe default only when the folder is small enough that every file really was opened. Numbers must be copied, never rounded, inferred or estimated - and a figure that appears in two files with different values is a contradiction to report, not one to average.
