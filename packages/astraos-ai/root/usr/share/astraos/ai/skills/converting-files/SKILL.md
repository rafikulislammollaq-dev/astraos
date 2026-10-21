# Converting files

keywords: convert, conversion, pdf, jpg, jpeg, png, image, photo, picture, document, docx, odt, spreadsheet, csv, text, rescale, resize, rotate, format, change format
requires: soffice
when: the user wants a file in another format - a document as a PDF, a photo as a JPG, a spreadsheet as a PDF, a text file as a PDF, or a picture resized or rotated

---

## Steps

1. Say what the conversion is and what it will produce before doing it: the input
   file, the output format, the output file's name, and where it will be written.
2. Pick the tool by what the input is:
   * a document (`.docx`, `.odt`, `.rtf`, `.html`, a Writer file) or a
     spreadsheet (`.xlsx`, `.ods`, `.csv`) becomes a PDF with LibreOffice:
     `run_command` `soffice --headless --convert-to pdf --outdir "<folder>" "<file>"`
     - it writes the new file beside the old one, and it must not be told to
     overwrite it;
   * a picture (`.jpg`, `.jpeg`, `.png`, `.webp`, `.tiff`, `.bmp`) becomes another
     picture with ImageMagick: `run_command` `convert "<file>" -quality 90
     "<name>.jpg"` - and for a smaller file, resize as well:
     `run_command` `convert "<file>" -resize 1920x1920\> -quality 85 "<name>.jpg"`
     (the `>` is quoted so the shell does not read it as a redirect);
   * a plain text file becomes a PDF with LibreOffice as well: the same
     `soffice --headless --convert-to pdf` call works on `.txt` and `.md`;
   * a PDF becomes text with `pdftotext "<file>" -` and its page count with
     `pdfinfo "<file>"` - that is reading, not converting.
3. Check the result before reporting it: `ls -l "<output>"` for the size, and
   `file "<output>"` for the type. A conversion that produced nothing, or a zero
   byte file, is a failure - say so, and say what the tool printed.
4. Report it in one line: the output file's name, its size, and where it is. If
   the output is a PDF, say how many pages it has.
5. If the user asked for a *smaller* file, say what made it smaller (the quality
   setting, the pixel size) - a file that is smaller for an unexplained reason is
   not a conversion they can trust.

## Notes

Every conversion here writes a new file and leaves the original alone. Nothing is
overwritten: if the output name already exists, ask, or add a suffix, and say
which you did.

The tools are in the image: LibreOffice (Writer and Calc) for documents, ImageMagick
for pictures, poppler's `pdftotext` and `pdfinfo` for PDFs. `soffice` writes
nothing outside the folder it is given, and it must be given one.

`convert` is ImageMagick's picture tool. It is not the shell's `convert` (that is
the filesystem tool), and it is run by its full path when in doubt.
