# Django also sends these headers; nginx sets them for every response,
# so drop Django's copies to avoid sending each header twice.
proxy_hide_header X-Frame-Options;
proxy_hide_header X-Content-Type-Options;
proxy_hide_header Referrer-Policy;
