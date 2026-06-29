# =============================================================================
# UDSM Student Support AI — Frontend Dockerfile
# =============================================================================

FROM nginx:1.27-alpine

# Remove default nginx static assets
RUN rm -rf /usr/share/nginx/html/*

# Copy the custom Nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy the static HTML, JS, and CSS files
COPY frontend/ /usr/share/nginx/html/

EXPOSE 80
