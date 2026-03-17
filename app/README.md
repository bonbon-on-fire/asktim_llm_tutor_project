# Transcript Viewer

Flask app to navigate and read tutor–student transcripts with GPT and Claude evaluation grades.

## Run

From the **repo root**:

```bash
cd app && python -m flask --app app run -p 5001
```

Or:

```bash
python app/app.py
```

Then open http://127.0.0.1:5001

## Features

- **Dashboard**: Grade distribution charts (GPT and Claude evaluators) and a sortable table of all conversations.
- **Transcript reader**: Read full conversation with metadata, exchanges (student, tutor, pedagogical reasoning), and both grade reports at the end.
