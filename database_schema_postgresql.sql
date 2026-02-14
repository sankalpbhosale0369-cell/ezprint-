-- EzPrint PostgreSQL Database Schema
-- This script creates all necessary tables for the EzPrint application
-- Compatible with PostgreSQL 12+

-- Create shopkeepers table
CREATE TABLE IF NOT EXISTS shopkeepers (
    id SERIAL PRIMARY KEY,
    shop_id VARCHAR(36) UNIQUE NOT NULL,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    shop_name VARCHAR(100) NOT NULL,
    shop_address VARCHAR(255),
    contact_number VARCHAR(20),
    shopkeeper_name VARCHAR(100),
    qr_code_path VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);

-- Create print_jobs table
CREATE TABLE IF NOT EXISTS print_jobs (
    id SERIAL PRIMARY KEY,
    job_id VARCHAR(36) UNIQUE NOT NULL,
    shop_id VARCHAR(36) NOT NULL,
    customer_ip VARCHAR(45),
    filename VARCHAR(255) NOT NULL,
    file_path VARCHAR(500) NOT NULL,
    file_size INTEGER NOT NULL,
    file_type VARCHAR(10) NOT NULL,
    page_range VARCHAR(50),
    copies INTEGER DEFAULT 1,
    page_size VARCHAR(20) DEFAULT 'A4',
    orientation VARCHAR(20) DEFAULT 'Portrait',
    print_side VARCHAR(20) DEFAULT 'Single',
    color_mode VARCHAR(20) DEFAULT 'Black & White',
    layout_pages INTEGER DEFAULT 1,
    layout_type VARCHAR(20) DEFAULT 'normal',
    total_pages INTEGER,
    status VARCHAR(20) DEFAULT 'Pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    error_message TEXT,
    amount REAL
);

-- Create printers table
CREATE TABLE IF NOT EXISTS printers (
    id SERIAL PRIMARY KEY,
    shop_id VARCHAR(36) NOT NULL,
    printer_name VARCHAR(100) NOT NULL,
    printer_id VARCHAR(100) NOT NULL,
    is_default BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create system_logs table
CREATE TABLE IF NOT EXISTS system_logs (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    level VARCHAR(20) NOT NULL,
    component VARCHAR(50) NOT NULL,
    message TEXT NOT NULL,
    details TEXT
);

-- Create shop_pricing table
CREATE TABLE IF NOT EXISTS shop_pricing (
    id SERIAL PRIMARY KEY,
    shop_id VARCHAR(36) UNIQUE NOT NULL,
    bw_single REAL DEFAULT 2.0,
    bw_double REAL DEFAULT 1.5,
    color_single REAL DEFAULT 10.0,
    color_double REAL DEFAULT 8.0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_print_jobs_shop_id ON print_jobs(shop_id);
CREATE INDEX IF NOT EXISTS idx_print_jobs_status ON print_jobs(status);
CREATE INDEX IF NOT EXISTS idx_print_jobs_created_at ON print_jobs(created_at);
CREATE INDEX IF NOT EXISTS idx_printers_shop_id ON printers(shop_id);
CREATE INDEX IF NOT EXISTS idx_system_logs_timestamp ON system_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_system_logs_level ON system_logs(level);
