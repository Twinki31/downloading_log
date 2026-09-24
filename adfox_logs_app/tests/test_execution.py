import ast
from datetime import date
import gzip
from pathlib import Path
import tempfile
import unittest

import execution
from execution import run_s3_operation
from filtering import Rule
from operation_state import OperationState


class ExecutionTests(unittest.TestCase):
    def test_simulated_s3_download_reaches_filtering_and_completed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "2026_09_24_12.tsv.gz"
            destination = root / "result.tsv"
            state = OperationState()
            state.prepare()

            def downloader(*_args, progress, metadata, **_kwargs):
                metadata(100)
                progress(40)
                progress(60)
                with gzip.open(archive, "wt", encoding="utf-8") as output:
                    output.write("banner_id\n208684\n")
                return archive

            payload = run_s3_operation(
                state, selected_date=date(2026, 9, 24), hour=12, folder=root,
                endpoint="https://s3.example", bucket="bucket", prefix="prefix",
                profile="", proxy=False, archive=archive, destination=destination,
                rules=(Rule("banner_id", "Одно из значений", ("208684",)),),
                keep_raw=True, downloader=downloader,
            )
            state.complete(payload)

            self.assertEqual(state.snapshot().percent, 100.0)
            self.assertEqual(
                tuple(x for x in state.history() if x != "preparing"),
                ("idle", "downloading", "filtering", "completed"),
            )
            self.assertEqual(destination.read_text(encoding="utf-8"),
                             "banner_id\n208684\n")

    def test_worker_modules_do_not_import_streamlit(self):
        for path in (Path(execution.__file__), Path(execution.__file__).with_name("operation_state.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imports = {
                node.names[0].name
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
            }
            imports.update(
                node.module for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module
            )
            self.assertNotIn("streamlit", imports)


if __name__ == "__main__":
    unittest.main()
