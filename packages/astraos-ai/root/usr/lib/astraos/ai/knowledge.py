"""The knowledge the assistant reads, and the index it is retrieved through.

WHY A SHIPPED LIBRARY AND NOT THE INTERNET

A small model asked "how do I do X on this machine" does not know less than a
large one - it knows nothing, in the same direction. What fixes that is not a
bigger model, it is a corpus that is already on the disk: this distribution's
own documentation, rewritten as short procedures the assistant can quote, plus
skills for the work people actually do. Retrieval turns a 1B model into an
assistant that can cite, and turns a 4B model into one that is not guessing.

WHY SQLITE FTS5 AND NOT EMBEDDINGS

An embedding model is another download, another model to load, another 300 MB of
RAM, and a vector index that has to be written into a package. BM25 in SQLite
FTS5 is in the standard library, needs no model, indexes in milliseconds at this
corpus size, and ranks a short factual passage above a waffly one - which is what
"how do I set the DNS" needs and what cosine similarity over a 384-dim vector is
not obviously better at when the whole corpus is a few hundred short documents.
The honest caveat is in the docstring of search(): BM25 matches words, so a
question about "nameserver" will not retrieve a passage that only ever says
"DNS server", which is why every skill and knowledge entry also carries
keywords chosen for that.

WHY THE INDEX IS BUILT AT RUN TIME AND NOT SHIPPED

A .db file in a .deb is a binary that nobody can read, diff or review, and it
goes stale the moment the text next to it changes. The index is built from the
corpus on first use and rebuilt whenever any file's mtime or size changes - a
few milliseconds for this corpus - so the packaged text is the single source of
truth and the index can never disagree with it.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import time
from pathlib import Path

from . import config as _config

# Where the corpus lives: read-only, shipped by the package. Everything in here
# is text this distribution is willing to stand behind.
SHARE_DIR = _config.PATHS.share_dir
KNOWLEDGE_DIR = SHARE_DIR / "knowledge"
SKILLS_DIR = SHARE_DIR / "skills"

# The database, in the user's data directory. Derived from the corpus root and
# the package version, so a rebuilt image with a different corpus does not reuse
# an index built from the old one.
DB_PATH = _config.PATHS.models_dir.parent / "knowledge.sqlite3"

# How many passages to return. Five is enough to give the model something to
# quote and few enough that it fits in a 4096-token context next to the question.
PASSAGE_LIMIT = 5

# What an index rebuild costs, in files. Above this the index is rebuilt in the
# background instead of in front of the user, which for this corpus means it
# never is - but the ceiling is stated so that adding 500 documents later is a
# decision someone makes on purpose.
REBUILD_FILE_LIMIT = 400


class Index:
    """The FTS5 index over the shipped knowledge and the skills.

    One index, not two. A skill is a knowledge entry that can also be run, so a
    question about "rotate the screen" should be able to find the skill for it
    without the caller knowing in advance which side of the line it falls on.
    """

    def __init__(self, path: Path | None = None):
        self.path = Path(path or DB_PATH)
        self._connection: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        if self._connection is not None:
            return self._connection
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path), timeout=10)
        # The index is disposable: it is rebuilt from the corpus whenever the
        # corpus changes, so a crash mid-write must not leave a state that a
        # user has to repair.
        connection.execute("PRAGMA journal_mode=MEMORY")
        connection.execute("PRAGMA synchronous=OFF")
        self._connection = connection
        return connection

    def close(self) -> None:
        if self._connection is not None:
            try:
                self._connection.close()
            finally:
                self._connection = None

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS entries (
        id          TEXT PRIMARY KEY,
        kind        TEXT NOT NULL,      -- knowledge | skill
        title       TEXT NOT NULL,
        keywords    TEXT NOT NULL,
        body        TEXT NOT NULL,
        source      TEXT NOT NULL,
        signature   TEXT NOT NULL
    );
    CREATE VIRTUAL TABLE IF NOT EXISTS passages USING fts5(
        title, keywords, body,
        tokenize = 'porter unicode61'
    );
    """

    def create(self) -> None:
        connection = self._connect()
        connection.executescript(self.SCHEMA)
        connection.commit()

    # ------------------------------------------------------------------
    # What the corpus is made of
    # ------------------------------------------------------------------

    def _signature(self, path: Path, body: str) -> str:
        """A fingerprint of one file: its size, its mtime and its text.

        The text is in the signature so that a file rewritten to the same length
        inside the same second is still noticed. mtime alone is the usual choice
        and it is not enough here: the corpus is installed from a .deb whose
        files all carry the build's timestamps, so several files can share one
        and a checkout can carry yesterday's.
        """
        try:
            stat = path.stat()
            stamp = f"{stat.st_size}:{stat.st_mtime_ns}"
        except OSError:
            stamp = "missing"
        return hashlib.sha256(f"{stamp}:{body}".encode("utf-8")).hexdigest()[:32]

    def _iter_source_files(self) -> list[tuple[Path, str]]:
        """Every markdown file in the corpus, with its kind."""
        found: list[tuple[Path, str]] = []
        for directory, kind in ((KNOWLEDGE_DIR, "knowledge"), (SKILLS_DIR, "skill")):
            if not directory.is_dir():
                continue
            for path in sorted(directory.rglob("*.md")):
                found.append((path, kind))
        return found

    def _split_entry(self, path: Path, body: str) -> tuple[str, str, str]:
        """The title, the keywords and the body of one markdown file.

        The title is the first heading, the keywords are a line that begins with
        "keywords:" (a colon-separated list, which is the one format that both a
        human and a shell one-liner can produce), and the body is everything
        after them. A file with no heading is indexed by its file name rather
        than skipped: a knowledge base that silently omits the files it could
        not parse is a knowledge base nobody can trust.
        """
        # The default title is the file name. The first H1 in the file replaces
        # it, regardless of what the file is called, because the heading is what
        # the author wrote and the file name is what a directory listing needs.
        seen_heading = False
        title = path.stem.replace("-", " ").replace("_", " ").strip()
        keywords = ""
        lines = []
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith("# ") and not seen_heading:
                seen_heading = True
                title = stripped[2:].strip()
                continue
            if stripped.lower().startswith("keywords:") and not keywords:
                keywords = stripped.split(":", 1)[1].strip().strip("`").strip()
                continue
            lines.append(line)
        return title, keywords, "\n".join(lines).strip()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def up_to_date(self) -> bool:
        """True when the index matches the files on disk right now.

        Cheap: it fingerprints the files and compares, so the common case is one
        directory walk and one SELECT.
        """
        connection = self._connect()
        self.create()
        try:
            rows = dict(connection.execute("SELECT id, signature FROM entries"))
        except sqlite3.DatabaseError:
            return False
        files = self._iter_source_files()
        if set(rows) != {self._entry_id(path) for path, _ in files}:
            return False
        for path, _kind in files:
            try:
                body = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if rows.get(self._entry_id(path)) != self._signature(path, body):
                return False
        return True

    def _entry_id(self, path: Path) -> str:
        """A stable id for a file, derived from its path inside the corpus."""
        try:
            relative = path.relative_to(SHARE_DIR)
        except ValueError:
            relative = path
        return str(relative).replace("\\", "/")

    def build(self) -> int:
        """Rebuild the index from the corpus. Returns how many entries it holds.

        A full rebuild rather than an incremental one: the corpus is a few
        hundred short files, the whole pass takes milliseconds, and a rebuild
        can never leave a deleted passage behind - which an incremental update
        can, and which is exactly the kind of staleness that makes an assistant
        confidently quote a procedure this distribution no longer ships.
        """
        connection = self._connect()
        self.create()
        files = self._iter_source_files()
        if len(files) > REBUILD_FILE_LIMIT:
            # Not a limit that is enforced anywhere but a fact worth stating in
            # the log: past this size the first-use cost is no longer free.
            _log(f"indexing {len(files)} passages")

        with connection:
            connection.execute("DELETE FROM entries")
            connection.execute("DELETE FROM passages")
            for path, kind in files:
                try:
                    body = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                title, keywords, text = self._split_entry(path, body)
                if not text:
                    continue
                entry_id = self._entry_id(path)
                connection.execute(
                    "INSERT INTO entries VALUES (?,?,?,?,?,?,?)",
                    (
                        entry_id,
                        kind,
                        title,
                        keywords,
                        text,
                        str(path),
                        self._signature(path, body),
                    ),
                )
                connection.execute(
                    "INSERT INTO passages (title, keywords, body) VALUES (?,?,?)",
                    (title, keywords, text),
                )
        return connection.execute("SELECT count(*) FROM entries").fetchone()[0]

    def ensure(self) -> int:
        """The index, built if it is stale. The one call every caller makes."""
        if not self.up_to_date():
            return self.build()
        return self._connect().execute("SELECT count(*) FROM entries").fetchone()[0]

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, query: str, limit: int = PASSAGE_LIMIT) -> list[dict]:
        """The passages that answer a question, best first.

        BM25 over the title, the keywords and the body. The two limits that
        matter for honesty are both applied here:

          * A query that matches nothing returns []. It does not return "the
            closest thing", and the caller must not fill the gap itself - the
            difference between "I could not find that in the knowledge base"
            and a plausible-sounding answer is the difference between an
            assistant and a liar.
          * A passage is never truncated to fit. A procedure cut in half is
            worse than a procedure that was not retrieved, because the user
            follows it as far as it goes.
        """
        self.ensure()
        connection = self._connect()
        query = (query or "").strip()
        if not query:
            return []

        # FTS5 query syntax: a bare word is a term, and anything that is not a
        # plain identifier is stripped rather than being handed to the parser,
        # which would answer a question phrased with a colon - "dns: how" - by
        # raising instead of searching.
        terms = re.findall(r"[A-Za-z0-9_.-]+", query)
        if not terms:
            return []
        match = " OR ".join(f'"{term}"' for term in terms)

        try:
            rows = connection.execute(
                "SELECT entries.id, entries.kind, entries.title, entries.keywords,"
                "       entries.body, entries.source,"
                # Column weights, and they are the point: a keyword an author
                # chose so a question would find it is worth more than the same
                # word turning up in prose. Without this, "install a new
                # program" ranked the email skill first, because its body says
                # "new" a lot.
                "       bm25(passages, 2.0, 5.0, 1.0) AS rank"
                " FROM passages JOIN entries ON entries.rowid = passages.rowid"
                " WHERE passages MATCH ?"
                " ORDER BY rank LIMIT ?",
                (match, int(limit)),
            ).fetchall()
        except sqlite3.OperationalError:
            # A matcher error (an unmatched quote, a term the tokenizer mangles)
            # is a search that found nothing, not a crash in the middle of a
            # plan.
            return []

        passages = []
        for entry_id, kind, title, keywords, body, source, _rank in rows:
            passages.append(
                {
                    "id": entry_id,
                    "kind": kind,
                    "title": title,
                    "keywords": keywords,
                    "body": body,
                    "source": source,
                }
            )
        return passages


def _log(message: str) -> None:
    import sys

    print(f"astra-ai: {message}", file=sys.stderr)


# One shared index. SQLite handles the concurrency; a second connection to the
# same file from the same process is a way to get "database is locked" instead of
# an answer.
_INDEX: Index | None = None


def index() -> Index:
    global _INDEX
    if _INDEX is None:
        _INDEX = Index()
    return _INDEX


def search(query: str, limit: int = PASSAGE_LIMIT) -> list[dict]:
    """Search the corpus. The function every other module imports."""
    return index().search(query, limit=limit)


def for_prompt(query: str, limit: int = PASSAGE_LIMIT) -> str:
    """The retrieved knowledge as text a model can read and quote.

    Each passage is labelled with where it came from, because a citation the
    user can check is the whole point of retrieval: an assistant that says "the
    knowledge base says" without naming the file is asking to be trusted, and
    the user has no way to grant that trust they can act on.
    """
    passages = search(query, limit=limit)
    if not passages:
        return ""
    blocks = []
    for passage in passages:
        blocks.append(
            f"[{passage['id']}]\n{passage['title']}\n{passage['body']}"
        )
    return "\n\n---\n\n".join(blocks)


def stats() -> dict:
    """What the index holds, for `astra ai knowledge`.

    ensure() runs FIRST. A count of a database that has not been built yet is a
    count of zero with no way to tell that apart from an empty corpus, and the
    command's first line would then be a lie about what is installed.
    """
    installed = index().ensure()
    knowledge = _count(kind="knowledge")
    skills = _count(kind="skill")
    return {
        "installed": bool(knowledge or skills),
        "entries": installed,
        "knowledge": knowledge,
        "skills": skills,
        "index": str(index().path),
        "share_dir": str(SHARE_DIR),
    }


def _count(kind: str) -> int:
    try:
        return index()._connect().execute(
            "SELECT count(*) FROM entries WHERE kind = ?", (kind,)
        ).fetchone()[0]
    except sqlite3.DatabaseError:
        return 0
