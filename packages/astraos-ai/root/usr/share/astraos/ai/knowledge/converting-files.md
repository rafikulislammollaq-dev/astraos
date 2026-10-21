# Converting files on AstraOS

keywords: convert, pdf, jpg, jpeg, png, image, photo, document, docx, spreadsheet, csv, resize, rotate, format

The tools are in the image, and the assistant can run them for you (it shows you
the command first, and it never overwrites anything).

**A document or a spreadsheet becomes a PDF** - LibreOffice, headless:

    soffice --headless --convert-to pdf --outdir "<folder>" "<file>"

The new file is written beside the old one with the same name and a `.pdf`
ending. This works on `.docx`, `.odt`, `.rtf`, `.html`, `.xlsx`, `.ods`, `.csv`
and even a plain `.txt` or `.md` file. Writer and Calc are installed; Impress is
in the archive, so a `.pptx` needs `sudo apt install libreoffice-impress` first.

**A picture becomes another picture** - ImageMagick:

    convert "<file>" -quality 90 "<name>.jpg"          # PNG to JPG
    convert "<file>" -resize 1920x1920\> -quality 85 "<name>.jpg"   # and smaller
    convert "<file>" -rotate 90 "<name>.jpg"           # and turned

`-quality` is what makes a JPG smaller: 85 to 92 is a good range for photographs.
`-resize 1920x1920>` shrinks the longest side to at most 1920 pixels and keeps the
proportions. Note the `>`: it has to be quoted (`1920x1920\>`) so the shell does
not read it as a redirect.

**A PDF becomes text** - poppler:

    pdftotext "<file>" -        # the text, to the terminal
    pdfinfo "<file>"            # the page count, the size, the metadata

That is reading, not converting, and it needs no confirmation.

**The assistant can do all of this for you.** Ask it in a sentence - "turn this
spreadsheet into a PDF", "make a smaller JPG of this photo" - and it will run the
command, check the result and tell you the file's name and size. The commands that
change something are behind a confirmation, and it never overwrites a file that is
already there.

**What it will not do**: convert between video formats, rip audio, or produce a
PDF from a scanned page - the last one needs OCR (`tesseract-ocr`, in the archive)
and a scanned image is a picture, not text. Anything that would take hours or
need a download the assistant will not start on its own; it will tell you the
command instead.
