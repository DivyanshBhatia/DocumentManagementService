-- init.sql
USE document_management;

-- Create users table
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'user',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Create documents table
CREATE TABLE IF NOT EXISTS documents (
    sno INT AUTO_INCREMENT PRIMARY KEY,
    document_type VARCHAR(100) NOT NULL,
    document_owner VARCHAR(100) NOT NULL,
    document_number VARCHAR(50) UNIQUE NOT NULL,
    expiry_date DATE NOT NULL,
    action_due_date DATE NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- Insert sample users
INSERT INTO users (username, email, role) VALUES 
('admin', 'admin@company.com', 'admin'),
('owner', 'owner@company.com', 'owner'),
('user1', 'user1@company.com', 'user');

-- Insert sample documents
INSERT INTO documents (document_type, document_owner, document_number, expiry_date, action_due_date) VALUES 
('License', 'John Doe', 'LIC-001', '2025-12-31', '2025-12-15'),
('Certificate', 'Jane Smith', 'CERT-002', '2025-08-15', '2025-08-01'),
('Contract', 'Bob Johnson', 'CONT-003', '2025-09-30', '2025-09-15');