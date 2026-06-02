"""Group file summaries by directory for deterministic, directory-ordered rendering."""

from collections import defaultdict
from collections.abc import Iterable, Iterator
from pathlib import Path

from docspatch.schemas import FileSummary


def group_by_dir(summaries: Iterable[FileSummary]) -> Iterator[tuple[str, list[FileSummary]]]:
    """Yield each parent directory with its summaries, both in sorted order.

    Args:
        summaries: File summaries to group.

    Yields:
        Directory path and its summaries sorted by file path.
    """
    by_dir: dict[str, list[FileSummary]] = defaultdict(list)
    for summary in summaries:
        by_dir[str(Path(summary.path).parent)].append(summary)
    for directory in sorted(by_dir):
        yield directory, sorted(by_dir[directory], key=lambda s: s.path)
