# .env
# Database Configuration
DATABASE_URL=mysql+pymysql://username:password@localhost/document_management

# JWT Configuration
JWT_SECRET=your-super-secret-jwt-key-here-make-it-long-and-random

# Email Configuration for Reminders
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-email@gmail.com
SMTP_PASSWORD=your-app-password
ADMIN_EMAIL=admin@company.com

# Optional: Production settings
ENVIRONMENT=production