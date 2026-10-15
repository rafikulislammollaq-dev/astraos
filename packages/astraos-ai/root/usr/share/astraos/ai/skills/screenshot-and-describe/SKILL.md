# Screenshot And Describe The Screen

keywords: screenshot, screen, describe, windows, picture, image, capture, what is on my screen, see, look

when: the user wants a screenshot taken, asks what is on the screen, or asks what windows are open

---

## Steps
1. Take the picture with the `screenshot` action. It takes no arguments, captures the whole screen, saves a PNG under `~/Pictures/Screenshots/` and answers with the exact path it produced. Read that path - do not invent a file name.
2. List what was on screen with the `list_windows` action. It returns one line per open window, each an id and a title. That list is what makes the description checkable rather than a guess at pixel shapes.
3. Match the two: for each window in the list, say what it is in one line, and note which one is the largest or which is on top. A window whose title names a document names its document - use that.
4. If the user asked about one specific window, bring it forward with the `focus_window` action and a few words of its title. Use this only when asked; focusing a window changes what the user is looking at.
5. Never use `close_window`. It can lose unsaved work and it is the one action in this group that asks the user first, which means a step that closes a window to take a look inside it has already accepted that risk.
6. Tell the user where the file is: the path from step 1, which is already inside `~/Pictures/Screenshots/`. If they asked for it somewhere else, run_command `mkdir -p ~/Pictures` first, then move only the file the screenshot action just created with run_command `mv ~/Pictures/Screenshots/<file>.png ~/Pictures/`. Never overwrite a picture that was already there: if the destination would replace an existing file, say so and SHOW THE LIST AND WAIT FOR CONFIRMATION before running the mv.
7. Give the description as prose: the windows, which had focus, the time on the clock if it is visible, and anything obviously wrong (a dialog box, an error, an empty window). Do not claim to read small text at 100 percent zoom unless it is legible in the image.
8. Nothing is uploaded. There is no upload action, and a step that mentions a web address is wrong for this skill.

## Notes

The screenshot action is full-screen only - there is no region capture and no way to choose a window. If the user asked for one window, say the image includes the whole screen and describe the part they meant.

Screenshots are taken by `xfce4-screenshooter` on AstraOS, with `scrot` and ImageMagick's `import` as fallbacks. If none of them is installed the action says so and names the package; the fix (`astra install xfce4-screenshooter`) is one the user runs, because installing needs root and this assistant does not have it.

Describe what is visible, not what should be. A window title is evidence; a description of a window that is not in the list_windows output is a guess, and a guess in a report about the user's own screen is easy to catch and hard to forgive.
