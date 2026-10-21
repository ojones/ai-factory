def form_body(app, request_text, cap=None):
    return f"### App name\n\n{app}\n\n### What should change?\n\n{request_text}\n\n### Cost cap override (USD)\n\n{cap if cap else '_No response_'}\n"
