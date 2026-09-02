CREATE TABLE IF NOT EXISTS locations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    floor INT NOT NULL,
    zone_type VARCHAR(64) NOT NULL,
    zone_name VARCHAR(255) NULL,
    aisle INT NULL,
    table_no INT NULL,
    row_no INT NULL,
    position INT NULL,
    label VARCHAR(255) NOT NULL UNIQUE,
    location_type VARCHAR(32) NOT NULL DEFAULT 'pc_position',
    parent_id INT NULL,
    x DOUBLE NULL,
    y DOUBLE NULL,
    z DOUBLE NULL,
    is_restricted BOOLEAN NOT NULL DEFAULT FALSE,
    metadata TEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_location_position
        (floor, zone_type, zone_name, aisle, table_no, row_no, position),
    FOREIGN KEY (parent_id) REFERENCES locations(id) ON DELETE SET NULL,
    INDEX idx_locations_floor (floor),
    INDEX idx_locations_zone (zone_type, zone_name),
    INDEX idx_locations_type (location_type),
    INDEX idx_locations_coords (x, y, z)
);

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
    client_version VARCHAR(64) NULL,
    client_version_updated_at DATETIME NULL,
    location_id INT NULL,
    location_assignment_method VARCHAR(16) NULL,
    location_assignment_status VARCHAR(16) NULL,
    location_confidence DOUBLE NULL,
    location_verified BOOLEAN NOT NULL DEFAULT FALSE,
    location_assigned_at DATETIME NULL,
    location_assigned_by VARCHAR(255) NULL,
    location_last_calculated_at DATETIME NULL,
    location_source VARCHAR(64) NULL,
    location_evidence TEXT NULL,
    location_failure_reason VARCHAR(255) NULL,
    health_cpu_percent DOUBLE NULL,
    health_memory_percent DOUBLE NULL,
    health_disk_percent DOUBLE NULL,
    health_updated_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (location_id)
        REFERENCES locations(id)
        ON DELETE SET NULL,
    INDEX idx_clients_location_assignment
        (location_assignment_method, location_assignment_status),
    INDEX idx_clients_location_verified (location_verified)
);

CREATE TABLE IF NOT EXISTS client_location_history (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    client_id INT NOT NULL,
    location_id INT NOT NULL,
    assigned_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    unassigned_at DATETIME NULL,
    assigned_by VARCHAR(255) NULL,
    assignment_method VARCHAR(16) NULL,
    assignment_status VARCHAR(16) NULL,
    confidence DOUBLE NULL,
    verified BOOLEAN NOT NULL DEFAULT FALSE,
    source VARCHAR(64) NULL,
    evidence TEXT NULL,
    FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE,
    FOREIGN KEY (location_id) REFERENCES locations(id) ON DELETE RESTRICT,
    INDEX idx_location_history_client (client_id, assigned_at),
    INDEX idx_location_history_location (location_id, assigned_at),
    INDEX idx_location_history_method (assignment_method, assignment_status)
);

CREATE TABLE IF NOT EXISTS connections (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    client_id INT NOT NULL,
    connected_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    disconnected_at DATETIME NULL,
    FOREIGN KEY (client_id)
        REFERENCES clients(id)
        ON DELETE CASCADE,
    INDEX idx_connections_client (client_id),
    INDEX idx_connections_connected_at (connected_at)
);

CREATE TABLE IF NOT EXISTS activity_logs (
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

CREATE TABLE IF NOT EXISTS screenshots (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    client_id INT NOT NULL,
    command_id VARCHAR(100) NULL,
    requested_by VARCHAR(255) NULL,
    filename VARCHAR(255) NOT NULL,
    storage_path VARCHAR(512) NOT NULL,
    mime_type VARCHAR(100) NOT NULL,
    file_size BIGINT NOT NULL,
    device_name VARCHAR(255) NULL,
    captured_at DATETIME NULL,
    uploaded_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status ENUM('REQUESTED', 'CAPTURED', 'UPLOADED', 'FAILED') NOT NULL DEFAULT 'REQUESTED',
    FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE,
    INDEX idx_screenshots_client_time (client_id, uploaded_at),
    INDEX idx_screenshots_command (command_id)
);

CREATE TABLE IF NOT EXISTS packages (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    package_id VARCHAR(100) NOT NULL UNIQUE,
    filename VARCHAR(255) NOT NULL,
    size_bytes BIGINT NOT NULL,
    sha256 CHAR(64) NOT NULL,
    storage_path VARCHAR(512) NOT NULL,
    uploaded_by VARCHAR(255) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_packages_created_at (created_at)
);

CREATE TABLE IF NOT EXISTS actions (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    action_id VARCHAR(100) NOT NULL UNIQUE,
    action_type VARCHAR(64) NOT NULL,
    requested_by VARCHAR(255) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at DATETIME NULL,
    completed_at DATETIME NULL,
    expires_at DATETIME NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    parameters LONGTEXT NULL,
    result LONGTEXT NULL,
    error LONGTEXT NULL,
    INDEX idx_actions_action_type (action_type),
    INDEX idx_actions_status (status),
    INDEX idx_actions_created_at (created_at)
);

CREATE TABLE IF NOT EXISTS action_targets (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    action_id BIGINT NOT NULL,
    client_id INT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    sent_at DATETIME NULL,
    acknowledged_at DATETIME NULL,
    started_at DATETIME NULL,
    completed_at DATETIME NULL,
    result LONGTEXT NULL,
    error LONGTEXT NULL,
    target_order INT NOT NULL DEFAULT 0,
    FOREIGN KEY (action_id)
        REFERENCES actions(id)
        ON DELETE CASCADE,
    FOREIGN KEY (client_id)
        REFERENCES clients(id)
        ON DELETE CASCADE,
    UNIQUE KEY uq_action_targets_action_client (action_id, client_id),
    INDEX idx_action_targets_action (action_id),
    INDEX idx_action_targets_client (client_id),
    INDEX idx_action_targets_status (status)
);

CREATE TABLE IF NOT EXISTS alerts (
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
    INDEX idx_alert_client (client_id),
    INDEX idx_alert_time (detected_at),
    INDEX idx_alert_status (status)
);

CREATE TABLE IF NOT EXISTS forbidden_processes (
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

CREATE TABLE IF NOT EXISTS working_hours (
    id INT AUTO_INCREMENT PRIMARY KEY,
    day_of_week TINYINT NOT NULL,
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE(day_of_week)
);

CREATE TABLE IF NOT EXISTS network_devices (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    mac_address VARCHAR(17) NOT NULL UNIQUE,
    ip_address VARCHAR(45) NULL,
    hostname VARCHAR(255) NULL,
    vendor VARCHAR(255) NULL,
    first_seen DATETIME NOT NULL,
    last_seen DATETIME NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_network_devices_last_seen (last_seen)
);

CREATE TABLE IF NOT EXISTS sensors (
    id INT AUTO_INCREMENT PRIMARY KEY,
    sensor_id VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    sensor_type VARCHAR(32) NOT NULL DEFAULT 'endpoint',
    client_id INT NULL,
    location_id INT NULL,
    x DOUBLE NULL,
    y DOUBLE NULL,
    z DOUBLE NULL,
    capabilities TEXT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'ONLINE',
    last_seen DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE SET NULL,
    FOREIGN KEY (location_id) REFERENCES locations(id) ON DELETE SET NULL,
    INDEX idx_sensors_type (sensor_type),
    INDEX idx_sensors_status (status)
);

CREATE TABLE IF NOT EXISTS network_device_observations (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    device_id BIGINT NOT NULL,
    source_type VARCHAR(32) NOT NULL,
    source_client_id INT NULL,
    sensor_id INT NULL,
    ip_address VARCHAR(45) NOT NULL,
    interface_name VARCHAR(255) NULL,
    entry_type VARCHAR(16) NOT NULL,
    rssi INT NULL,
    switch_port VARCHAR(64) NULL,
    raw_data TEXT NULL,
    observed_at DATETIME NOT NULL,
    received_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (device_id)
        REFERENCES network_devices(id)
        ON DELETE CASCADE,
    FOREIGN KEY (source_client_id)
        REFERENCES clients(id)
        ON DELETE SET NULL,
    FOREIGN KEY (sensor_id)
        REFERENCES sensors(id)
        ON DELETE SET NULL,
    INDEX idx_network_device_observations_device_time (device_id, observed_at),
    INDEX idx_network_device_observations_source_client (source_client_id),
    INDEX idx_network_device_observations_sensor (sensor_id)
);

CREATE TABLE IF NOT EXISTS device_location_estimates (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    device_id BIGINT NOT NULL UNIQUE,
    location_id INT NULL,
    x DOUBLE NULL,
    y DOUBLE NULL,
    z DOUBLE NULL,
    confidence DOUBLE NOT NULL DEFAULT 0.0,
    method VARCHAR(64) NOT NULL,
    supporting_sensor_ids TEXT NULL,
    calculated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (device_id) REFERENCES network_devices(id) ON DELETE CASCADE,
    FOREIGN KEY (location_id) REFERENCES locations(id) ON DELETE SET NULL,
    INDEX idx_estimates_location (location_id),
    INDEX idx_estimates_confidence (confidence)
);

CREATE TABLE IF NOT EXISTS device_location_events (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    device_id BIGINT NOT NULL,
    previous_location_id INT NULL,
    new_location_id INT NULL,
    previous_x DOUBLE NULL,
    previous_y DOUBLE NULL,
    previous_z DOUBLE NULL,
    new_x DOUBLE NULL,
    new_y DOUBLE NULL,
    new_z DOUBLE NULL,
    confidence DOUBLE NOT NULL DEFAULT 0.0,
    method VARCHAR(64) NOT NULL,
    reason VARCHAR(255) NULL,
    timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (device_id) REFERENCES network_devices(id) ON DELETE CASCADE,
    FOREIGN KEY (previous_location_id) REFERENCES locations(id) ON DELETE SET NULL,
    FOREIGN KEY (new_location_id) REFERENCES locations(id) ON DELETE SET NULL,
    INDEX idx_location_events_device_time (device_id, timestamp)
);

CREATE TABLE IF NOT EXISTS rogue_device_assessments (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    device_id BIGINT NOT NULL UNIQUE,
    rogue_score INT NOT NULL DEFAULT 0,
    is_rogue BOOLEAN NOT NULL DEFAULT FALSE,
    classification VARCHAR(32) NOT NULL DEFAULT 'UNKNOWN',
    risk_level ENUM('LOW', 'MEDIUM', 'HIGH', 'CRITICAL') NOT NULL DEFAULT 'LOW',
    reasons TEXT NULL,
    first_detected_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_evaluated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (device_id) REFERENCES network_devices(id) ON DELETE CASCADE,
    INDEX idx_rogue_score (rogue_score),
    INDEX idx_is_rogue (is_rogue),
    INDEX idx_rogue_risk (risk_level)
);

CREATE TABLE IF NOT EXISTS daily_network_scan_files (
    scan_date DATE NOT NULL PRIMARY KEY,
    file_path VARCHAR(512) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS device_classifications (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    device_id BIGINT NOT NULL UNIQUE,
    predicted_class VARCHAR(64) NOT NULL,
    confidence DOUBLE NOT NULL,
    model_version VARCHAR(64) NOT NULL,
    source ENUM('ML', 'RULE', 'HUMAN', 'HYBRID') NOT NULL DEFAULT 'ML',
    features_version VARCHAR(32) NOT NULL DEFAULT 'v1',
    evidence TEXT NULL,
    rule_prediction VARCHAR(64) NULL,
    ml_prediction VARCHAR(64) NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    probabilities TEXT NULL,
    classified_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (device_id) REFERENCES network_devices(id) ON DELETE CASCADE,
    INDEX idx_device_classifications_class (predicted_class),
    INDEX idx_device_classifications_confidence (confidence),
    INDEX idx_device_classifications_source (source),
    INDEX idx_device_classifications_status (status)
);

CREATE TABLE IF NOT EXISTS device_labels (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    device_id BIGINT NOT NULL,
    label VARCHAR(64) NOT NULL,
    source VARCHAR(32) NOT NULL DEFAULT 'ADMIN',
    confirmed_by VARCHAR(255) NULL,
    notes TEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (device_id) REFERENCES network_devices(id) ON DELETE CASCADE,
    INDEX idx_device_labels_device (device_id),
    INDEX idx_device_labels_label (label),
    INDEX idx_device_labels_created (created_at)
);

INSERT IGNORE INTO forbidden_processes (process_name, severity, enabled, description) VALUES ('discord', 'HIGH', TRUE, 'Social media/gaming communication platform - not authorized for work use');

-- day_of_week uses Python's datetime.weekday(): Monday=0 through Sunday=6.
-- The centre is open Saturday through Thursday, 09:30 (inclusive) to 18:00
-- (exclusive). Friday deliberately has no enabled schedule.
INSERT IGNORE INTO working_hours (day_of_week, start_time, end_time, enabled) VALUES
    (0, '09:30:00', '18:00:00', TRUE),
    (1, '09:30:00', '18:00:00', TRUE),
    (2, '09:30:00', '18:00:00', TRUE),
    (3, '09:30:00', '18:00:00', TRUE),
    (5, '09:30:00', '18:00:00', TRUE),
    (6, '09:30:00', '18:00:00', TRUE);

-- ── Milestone G: Bulk update tracking ─────────────────────────────────────────
-- bulk_updates: one row per bulk-update operation (covers N clients).
CREATE TABLE IF NOT EXISTS bulk_updates (
    id INT AUTO_INCREMENT PRIMARY KEY,
    bulk_update_id VARCHAR(255) NOT NULL UNIQUE,
    package_id VARCHAR(255) NOT NULL,
    target_selection_strategy VARCHAR(50) NOT NULL DEFAULT 'individual',  -- 'individual' | 'all'
    target_count INT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(255) NULL,
    INDEX idx_bulk_updates_id (bulk_update_id),
    INDEX idx_bulk_updates_package (package_id),
    INDEX idx_bulk_updates_created (created_at)
);

-- bulk_update_actions: one row per (bulk_update, client) pair.
-- status mirrors the corresponding actions row so the status endpoint can read
-- both tables without touching action_targets for every client.
CREATE TABLE IF NOT EXISTS bulk_update_actions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    bulk_update_id VARCHAR(255) NOT NULL,
    action_id VARCHAR(255) NOT NULL,
    client_id VARCHAR(50) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    result LONGTEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (bulk_update_id) REFERENCES bulk_updates(bulk_update_id) ON DELETE CASCADE,
    UNIQUE KEY uq_bulk_action (bulk_update_id, action_id),
    INDEX idx_bua_bulk_update (bulk_update_id),
    INDEX idx_bua_client (client_id),
    INDEX idx_bua_action (action_id)
);
