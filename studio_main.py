from pathlib import Path
import sys
import logging
import faulthandler
import os
from studio.runtime import isolate_process
isolate_process(Path(__file__).resolve().parent)
from studio.windows_identity import set_process_identity
set_process_identity()
from studio.app import main

if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    (root / 'user-data').mkdir(exist_ok=True)
    # Keep the handle open for native Qt/VLC crash diagnostics (also in pythonw).
    crash_log = (root / 'user-data' / f'studio.crash-{os.getpid()}.log').open('a', encoding='utf-8')
    faulthandler.enable(file=crash_log, all_threads=True)
    logging.basicConfig(filename=root / 'user-data' / 'studio.local.log', level=logging.WARNING,
                        encoding='utf-8', format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    def report_error(kind, error, trace):
        logging.error('Application exception', exc_info=(kind, error, trace))
        if sys.stderr:
            sys.__excepthook__(kind, error, trace)
    sys.excepthook = report_error
    raise SystemExit(main(root, '--demo' in sys.argv))
