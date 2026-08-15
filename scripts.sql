CREATE TABLE IF NOT EXISTS clients (
    id INT AUTO_INCREMENT PRIMARY KEY,
    client_id VARCHAR(50) NOT NULL UNIQUE,
    hostname VARCHAR(255),
    ip VARCHAR(45),
    mac VARCHAR(17) NOT NULL UNIQUE,
    os_system VARCHAR(100),
    os_release VARCHAR(100),
    os_version VARCHAR(255),
    os_machine VARCHAR(100),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS connections (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,

    client_id INT NOT NULL,

    connected_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    disconnected_at DATETIME NULL,

    FOREIGN KEY (client_id)
        REFERENCES clients(id)
        ON DELETE CASCADE,

    INDEX idx_connections_client (
        client_id
    ),

    INDEX idx_connections_connected_at (
        connected_at
    )
);
CREATE TABLE activity_logs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,

    client_id INT NOT NULL,

    file_path VARCHAR(500) NOT NULL,

    period VARCHAR(10),

    generated_at DATETIME,

    received_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (client_id)
        REFERENCES clients(id)
        ON DELETE CASCADE
);

CREATE TABLE alerts (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,

    client_id INT NOT NULL,

    log_id BIGINT NULL,

    alert_type VARCHAR(100) NOT NULL,

    severity ENUM(
        'LOW',
        'MEDIUM',
        'HIGH',
        'CRITICAL'
    ) NOT NULL DEFAULT 'MEDIUM',

    detected_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    activity_time DATETIME NULL,

    title VARCHAR(255) NOT NULL,

    description TEXT,

    status ENUM(
        'NEW',
        'ACKNOWLEDGED',
        'RESOLVED'
    ) NOT NULL DEFAULT 'NEW',

    FOREIGN KEY (client_id)
        REFERENCES clients(id)
        ON DELETE CASCADE,

    FOREIGN KEY (log_id)
        REFERENCES activity_logs(id)
        ON DELETE SET NULL,

    INDEX idx_alert_client (
        client_id
    ),

    INDEX idx_alert_time (
        detected_at
    ),

    INDEX idx_alert_status (
        status
    )
);
CREATE TABLE forbidden_processes (
    id INT AUTO_INCREMENT PRIMARY KEY,

    process_name VARCHAR(255) NOT NULL UNIQUE,

    severity ENUM(
        'LOW',
        'MEDIUM',
        'HIGH',
        'CRITICAL'
    ) NOT NULL DEFAULT 'HIGH',

    enabled BOOLEAN NOT NULL DEFAULT TRUE,

    description TEXT
);

CREATE TABLE working_hours (
    id INT AUTO_INCREMENT PRIMARY KEY,

    day_of_week TINYINT NOT NULL,

    start_time TIME NOT NULL,

    end_time TIME NOT NULL,

    enabled BOOLEAN NOT NULL DEFAULT TRUE,

    UNIQUE(day_of_week)
);