# What The Assistant Sends, And What It Does Not

keywords: privacy, network, upload, telemetry, offline, local, 127.0.0.1, lan mode, password, search_web, whisper, espeak, journal, what leaves the machine

The assistant runs on this computer. It binds to `127.0.0.1:8765` - localhost only - so
nothing outside the machine can reach it, and the model inference happens on the local
CPU through llama.cpp. The web page it serves is one HTML file with its styles and script
inline: it makes no request of any kind except to the server that served it, and there are
no fonts, scripts, trackers or analytics endpoints in it to fetch. That is a property the
distribution checks, and the page would not work on a machine with no internet
connection anyway. There is no telemetry, no crash reporting, no account, no cloud
provider and no API key to configure; there is no configuration in which the assistant
talks to a server belonging to AstraOS, because there is no such server.

Two things do leave the machine, and both are decisions you make rather than defaults you
inherit. The first is `astra ai start --lan`: it opens the same page to every device on
the local network, with no password and no TLS, so anyone who can reach your address can
read the conversation and ask questions. Actions still require a confirmation in the page
that is watching, so a stranger can propose but the person at the PC decides - and that is
the whole of the protection, which is why the server prints its warning line at startup and
why the right way to think about `--lan` is "a room I have unlocked for ten minutes", not
"a feature I have turned on". The second is `search_web`: that action hands the query to
your browser, where a web search obviously goes to the internet. It is deliberate - there
is no search in the action repertoire that reports results without doing that - and if you
asked the assistant something and it opened a browser, that request left the machine.

Voice is local, with one caveat worth knowing. Speech synthesis uses `espeak-ng` (or
`spd-say`) on this machine, and speech recognition through whisper.cpp runs on this
machine too: a recording made in the page is posted to `127.0.0.1` and transcribed there,
so the audio goes nowhere else. Where the browser offers its own speech recognition, the
page asks for on-device transcription; some browsers instead route audio to their vendor's
service, which is a browser behaviour outside AstraOS's control, and it is why the page's
promise is about its own requests and not about everything the browser does. If that
matters to you, use the recorded-audio path.

What the assistant writes down is also on this machine and never uploaded. Its journal
lives in `~/.local/share/astraos/ai/journal.sqlite3`, and it records the tasks it was
given, the steps it took and the commands it ran, so `astra ai journal` can answer "what
did you do" afterwards. Conversations are not persisted: a reload forgets the transcript,
which lived in the page's memory and in the model's context window and nowhere else. The
skills and knowledge it quotes are plain files under `/usr/share/astraos/ai/` and your own
under `~/.local/share/astraos/ai/`.

The honest boundary of all of this: the assistant runs as your user, with your rights and
no others, and there is no sandbox around it - no AppArmor profile, no container. It can
read your files and run commands in your name, which is exactly what makes it useful and
exactly why the action repertoire is a short fixed list, why anything destructive waits for
a confirmation in front of you, and why it refuses to run anything as root. A setup step
like `astra-ai setup --model NAME` does fetch a model from a third party - that is a
request to a server somewhere else, made by you, to get a file - but the assistant's own
operation never sends anything.
