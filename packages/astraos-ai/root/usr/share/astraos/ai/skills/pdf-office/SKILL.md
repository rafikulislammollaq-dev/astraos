# Reading And Converting A PDF

keywords: pdf, pdftotext, extract, extraction, text, ocr, scanned, tesseract, convert, docx, soffice, poppler, document, pages

requires: pdftotext, soffice

when: the user wants the text out of a PDF, wants a document converted, or wants to know what is inside a file they cannot open

---

## Steps

1. Find the file and confirm it is really there: `search_files` with part of its name, then `read_file` if it is a text file. `read_pdf` names a missing file rather than returning an empty answer.
2. Extract the text: `read_pdf` with the path. It runs `pdftotext -layout` with the output sent to standard output, which the action captures and returns.
3. Read what came back. If it is a page or more of readable text, quote from it directly, name the file, and say how many pages it has if `pdftotext` printed page breaks.
4. If the extraction comes back empty, or a handful of characters for a file that is clearly tens of pages, it is a scanned PDF: it has no text layer at all. `read_pdf` says so; repeat that rather than inventing contents.
5. For a scanned page, render the first page to a PNG: run_command `pdftoppm -r 300 -png -f 1 -l 1 ~/Documents/<file>.pdf /tmp/astra-page`. One page at a time; a hundred pages at 300 dpi fills the disk.
6. Run OCR on that image: run_command `tesseract /tmp/astra-page-1.png stdout`. The word `stdout` is the output file name and means "print it here" - it is not a mistake, do not replace it with a path.
7. To convert a document the other way, use LibreOffice headless: run_command `soffice --headless --convert-to docx --outdir ~/Documents ~/Documents/<file>.pdf`. Replace `docx` with `txt` or `pdf` as asked. The `--outdir` directory must exist, and the input is never written to.
8. Report the result: the file's name, how many pages it has, what it says, and - when you converted it - the exact path of the new file. Do not summarise a file you failed to read.

## Notes

Extraction is read-only, every time. `read_pdf` reads a file from the user's folders and writes nothing; `soffice --convert-to` writes a new file in a directory the user named and leaves the original alone. If a step looks like it needs a writable copy of the input, that step is wrong - stop and re-read this one.

`read_pdf` reports a missing `pdftotext` with the package to install (`poppler-utils`). On AstraOS that package is installed; if it is genuinely missing, the answer is `astra install poppler-utils`, which the user must run because it needs root. `tesseract` (package `tesseract-ocr`, plus `tesseract-ocr-eng` for English) is not part of the image and is only needed for scanned pages; if it is missing, say OCR is unavailable and offer the rendered PNG instead.

Two flags that are worth knowing: `-layout` keeps the columns of a table roughly where they were, which is the difference between a readable document and one long line of mush; `-f 1 -l 1` on pdftoppm is the page range, first and last. There is no step here that renames, moves or deletes a PDF.
