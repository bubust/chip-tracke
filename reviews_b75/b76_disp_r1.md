B76 round-1 dispositions:
Gemini F1 (TX 30m target 38 bars): REJECTED - design principle is ~9 bars per leg on every chart; TX uses the same m as B75 did for 60m (pre-registered).
Gemini F2 numeric range: ACCEPTED (§4.5 range object). Gemini F3 tf-specific theta: ACCEPTED (planned). Gemini F4 risk overflow: ACCEPTED (max 3 risks + 'N more').
Groq F1 calibration look-ahead: REJECTED - parameter chosen once on a past window and fixed; live theta uses only past ATR (same as B74/B75).
Groq F2 advice fallbacks: ACCEPTED (§4.6). Groq F3 snapshot version: ACCEPTED as v:76 (frontend has no generic key iteration).
Groq F4 tf persistence: ACCEPTED (+UI test). Groq F5 30m disclaimer: ACCEPTED. Groq F6 collapse advice on mobile: REJECTED (user asked to see it on top; UI test checks no horizontal overflow).
