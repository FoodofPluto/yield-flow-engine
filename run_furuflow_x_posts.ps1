$env:FURUFLOW_X_MODE="signals"
$env:FURUFLOW_X_POST_LIVE="false"
python .\post_to_x.py

$env:FURUFLOW_X_MODE="daily"
python .\post_to_x.py
