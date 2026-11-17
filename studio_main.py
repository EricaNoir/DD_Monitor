from pathlib import Path
import sys
import logging
from studio.app import main

if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    (root / 'user-data').mkdir(exist_ok=True)
    logging.basicConfig(filename=root / 'user-data' / 'studio.local.log', level=logging.WARNING,
                        encoding='utf-8', format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    def report_error(kind, error, trace):
        logging.error('Application exception', exc_info=(kind, error, trace))
        if sys.stderr:
            sys.__excepthook__(kind, error, trace)
    sys.excepthook = report_error
    raise SystemExit(main(root, '--demo' in sys.argv))
