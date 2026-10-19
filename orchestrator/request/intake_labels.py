# The labels that mark an Intake and start it.
NEW_APP_INTAKE = "new-app-intake"
UPDATE_APP_INTAKE = "update-app-intake"
START = "proceed-with-change"


def app_label(app):
    return f"app:{app}"
