# Windows applications on AstraOS

keywords: windows apps, compatibility, word, excel, powerpoint, photoshop, teams, zoom, spotify, netflix, discord, telegram, autocad, minecraft, onedrive, office, libreoffice, gimp, wine, browser

AstraOS is Debian 13 with an Xfce desktop. An application you know from Windows
runs here in one of four ways, and this page says which for the applications
people actually ask about. The four verdicts are:

- **native** - there is a program for Linux, and it is in Debian's archive (some
  of them are already in this image);
- **Wine** - the Windows program runs under Wine, which is in this image. Wine
  runs a great many applications and a few of them badly;
- **browser** - the vendor's own web version does the job, in Firefox ESR;
- **no** - there is no honest way to run it here.

| Application | Native | Wine | Browser | The honest note |
|---|---|---|---|---|
| Microsoft Word | LibreOffice Writer (in the image) | yes, with a licence | Microsoft 365 | `.docx` opens and edits; the layout drifts on complex documents, and macros do not run |
| Microsoft Excel | LibreOffice Calc (in the image) | yes, with a licence | Microsoft 365 | Formulas and most formatting work; VBA macros do not |
| Microsoft PowerPoint | LibreOffice Impress (in the archive) | yes, with a licence | Microsoft 365 | `.pptx` opens; animations and fonts drift |
| Outlook | Thunderbird (in the archive) | yes, with a licence | Microsoft 365 | Mail and calendars work; the add-ins do not |
| OneNote | no | no | Microsoft 365 | The web version is the only version that works |
| Photoshop | GIMP (in the archive) | no - Adobe's installer does not run | yes (Photopea, Adobe's own web app) | Layers, masks and curves transfer; RAW files and plugins are the gaps |
| GIMP | GIMP (in the archive) | - | yes | The native program is the better answer |
| Illustrator | Inkscape (in the archive) | no | yes | SVG is the common ground; a `.ai` file opens with the right extensions |
| Lightroom | darktable (in the archive) | no | no | RAW development works; the catalogue and the presets do not carry |
| Premiere / DaVinci Resolve | Kdenlive (in the archive) | no | no | A different program, not the same one; Resolve has no Linux build |
| AutoCAD | no | no | read-only viewer | There is no honest substitute for the real thing; a web viewer cannot draw |
| Microsoft Teams | no | no | yes | The browser is the answer, and the official answer |
| Zoom | no | no | yes | Same |
| Discord | no | no | yes | The browser version is the supported one |
| Telegram | no | no | yes | The web version works; the desktop client is a separate download |
| WhatsApp | no | no | yes | The web version works, tied to the phone |
| Spotify | no | no | yes | The web player is the same product |
| Netflix, Disney+, Prime Video | no | no | yes | DRM in the browser is the supported path |
| Spotify / music offline | no | no | - | The web player needs a connection; for offline music, download it with `youtube-dl` or keep the files |
| Chrome | Chromium (in the archive) | no | - | Firefox ESR is in the image already; Chromium is in the archive |
| Edge | no | no | yes | Any browser opens the web version; the desktop program is not in Debian |
| VS Code | the Linux build from Microsoft's site | no | - | Microsoft's own Linux build; it is not in Debian's archive |
| Docker | in the archive | no | - | `sudo apt install docker.io` and it works |
| Notepad | Mousepad (in the image) | - | - | The image's text editor |
| Windows Terminal | xfce4-terminal (in the image) | - | - | The image's terminal |
| Minecraft (Java) | a Java runtime is in the archive | the launcher runs under Wine | - | It needs a Mojang account and some effort; it is not a first-class path |
| Candy Crush and other phone games | no | no | a few | There is no native way, and pretending otherwise would be a lie |
| iTunes | no | no | yes (Apple Music) | The library sync is the part that does not carry |
| Windows Sandbox, Hyper-V | no | no | no | These are features of Windows, not programs |
| Excel VBA, Adobe plugins | no | no | - | Nothing runs them here |

**How to check an application that is not in this table.** The archive is the
answer: `apt-cache policy <name>` says whether a package exists and which
version. `apt-cache search <name>` finds it when the name is not the one the
vendor uses. If the archive has nothing, check the two remaining roads: Wine is
in this image (`wine <setup.exe>`), and the vendor's own web version usually
works.

**What is not in this table** is a list of everything else, and the honest answer
for an application that is not here is "it depends, and I would have to check" -
not "it will work" and not "it will not".

**The second question people ask** is whether their *files* will open. They
usually will: `.docx`, `.xlsx`, `.pptx`, `.pdf`, `.jpg`, `.mp4` and `.txt` are
all read natively, and the formats that are not (`.pages`, `.key`, `.one`) are
either exported by their own programs or readable after an export. The
*install-extra-software* page has the commands.
