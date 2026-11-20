FROM node:20-alpine

WORKDIR /app

# Install dependencies based on the preferred package manager
COPY package.json package-lock.json* ./
RUN npm install

# Copy source files
COPY . .

# Expose Next.js port
EXPOSE 3000

ENV PORT 3000
ENV HOSTNAME "0.0.0.0"

# Development server
CMD ["npm", "run", "dev"]
