USE EntityResolutionDB;
GO

-- ============================================================================
-- 1. PIPELINE RUNS
-- Tracks batch executions, file metadata, status, and aggregate metrics.
-- ============================================================================
IF OBJECT_ID('dbo.pipeline_runs', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.pipeline_runs (
        run_id UNIQUEIDENTIFIER PRIMARY KEY,
        source_file NVARCHAR(500) NULL,
        source_file_hash VARCHAR(64) NULL,
        start_time DATETIME2 NOT NULL,
        end_time DATETIME2 NULL,
        run_status VARCHAR(20) NOT NULL DEFAULT 'RUNNING',
        input_count INT NOT NULL DEFAULT 0,
        processed_count INT NOT NULL DEFAULT 0,
        new_entity_count INT NOT NULL DEFAULT 0,
        mapped_count INT NOT NULL DEFAULT 0,
        unresolved_count INT NOT NULL DEFAULT 0,
        rejected_count INT NOT NULL DEFAULT 0,
        duplicate_count INT NOT NULL DEFAULT 0,
        conflict_count INT NOT NULL DEFAULT 0,
        failure_reason NVARCHAR(2000) NULL,

        CONSTRAINT CK_pipeline_run_status
            CHECK (run_status IN ('RUNNING', 'SUCCESS', 'FAILED'))
    );
END
ELSE
BEGIN
    -- Non-destructive column additions for existing installations
    IF COL_LENGTH('dbo.pipeline_runs', 'source_file_hash') IS NULL
    BEGIN
        ALTER TABLE dbo.pipeline_runs ADD source_file_hash VARCHAR(64) NULL;
    END

    IF COL_LENGTH('dbo.pipeline_runs', 'source_file') IS NULL
    BEGIN
        ALTER TABLE dbo.pipeline_runs ADD source_file NVARCHAR(500) NULL;
    END

    IF COL_LENGTH('dbo.pipeline_runs', 'new_entity_count') IS NULL
    BEGIN
        ALTER TABLE dbo.pipeline_runs ADD new_entity_count INT NOT NULL DEFAULT 0;
    END

    IF COL_LENGTH('dbo.pipeline_runs', 'duplicate_count') IS NULL
    BEGIN
        ALTER TABLE dbo.pipeline_runs ADD duplicate_count INT NOT NULL DEFAULT 0;
    END
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_pipeline_runs_hash' AND object_id = OBJECT_ID('dbo.pipeline_runs'))
BEGIN
    CREATE INDEX IX_pipeline_runs_hash ON dbo.pipeline_runs(source_file_hash);
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_pipeline_runs_status_time' AND object_id = OBJECT_ID('dbo.pipeline_runs'))
BEGIN
    CREATE INDEX IX_pipeline_runs_status_time ON dbo.pipeline_runs(run_status, start_time DESC);
END
GO


-- ============================================================================
-- 2. SOURCE RECORDS
-- Raw staging records loaded directly from incoming batches.
-- ============================================================================
IF OBJECT_ID('dbo.source_records', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.source_records (
        source_record_id BIGINT IDENTITY(1,1) PRIMARY KEY,
        run_id UNIQUEIDENTIFIER NOT NULL,
        source_system VARCHAR(50) NOT NULL,
        source_id VARCHAR(100) NULL,
        full_name NVARCHAR(200) NULL,
        email NVARCHAR(320) NULL,
        phone VARCHAR(30) NULL,
        source_updated_at DATETIME2 NULL,
        source_file NVARCHAR(500) NOT NULL,
        ingested_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),

        CONSTRAINT FK_source_run
            FOREIGN KEY (run_id)
            REFERENCES dbo.pipeline_runs(run_id)
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_source_system_id' AND object_id = OBJECT_ID('dbo.source_records'))
BEGIN
    CREATE INDEX IX_source_system_id ON dbo.source_records(source_system, source_id);
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_source_records_run_id' AND object_id = OBJECT_ID('dbo.source_records'))
BEGIN
    CREATE INDEX IX_source_records_run_id ON dbo.source_records(run_id);
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_source_records_email' AND object_id = OBJECT_ID('dbo.source_records'))
BEGIN
    CREATE INDEX IX_source_records_email ON dbo.source_records(email);
END
GO


-- ============================================================================
-- 3. RECORD VALIDATION RESULTS
-- Audit log of validation classifications for each source record.
-- ============================================================================
IF OBJECT_ID('dbo.record_validation_results', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.record_validation_results (
        validation_id BIGINT IDENTITY(1,1) PRIMARY KEY,
        source_record_id BIGINT NOT NULL,
        run_id UNIQUEIDENTIFIER NOT NULL,
        validation_status VARCHAR(20) NOT NULL,
        validation_reason VARCHAR(100) NULL,
        validated_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),

        CONSTRAINT FK_validation_source
            FOREIGN KEY (source_record_id)
            REFERENCES dbo.source_records(source_record_id),

        CONSTRAINT FK_validation_run
            FOREIGN KEY (run_id)
            REFERENCES dbo.pipeline_runs(run_id),

        CONSTRAINT CK_validation_status
            CHECK (validation_status IN ('VALID', 'REJECTED', 'UNRESOLVED', 'DUPLICATE'))
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_validation_run_status' AND object_id = OBJECT_ID('dbo.record_validation_results'))
BEGIN
    CREATE INDEX IX_validation_run_status ON dbo.record_validation_results(run_id, validation_status);
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_validation_source_record' AND object_id = OBJECT_ID('dbo.record_validation_results'))
BEGIN
    CREATE INDEX IX_validation_source_record ON dbo.record_validation_results(source_record_id);
END
GO


-- ============================================================================
-- 4. CANONICAL ENTITIES
-- The single source of truth / golden records created from resolved identities.
-- ============================================================================
IF OBJECT_ID('dbo.canonical_entities', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.canonical_entities (
        canonical_id VARCHAR(50) PRIMARY KEY,
        full_name NVARCHAR(200) NULL,
        normalized_email NVARCHAR(320) NULL,
        normalized_phone VARCHAR(30) NULL,
        created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_canonical_normalized_email' AND object_id = OBJECT_ID('dbo.canonical_entities'))
BEGIN
    CREATE INDEX IX_canonical_normalized_email ON dbo.canonical_entities(normalized_email);
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_canonical_name_phone' AND object_id = OBJECT_ID('dbo.canonical_entities'))
BEGIN
    CREATE INDEX IX_canonical_name_phone ON dbo.canonical_entities(full_name, normalized_phone);
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_canonical_normalized_phone' AND object_id = OBJECT_ID('dbo.canonical_entities'))
BEGIN
    CREATE INDEX IX_canonical_normalized_phone ON dbo.canonical_entities(normalized_phone);
END
GO


-- ============================================================================
-- 5. CURRENT CANONICAL MAPPINGS
-- Active linkage between a source system key and its resolved canonical entity.
-- ============================================================================
IF OBJECT_ID('dbo.canonical_mappings', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.canonical_mappings (
        mapping_id BIGINT IDENTITY(1,1) PRIMARY KEY,
        source_system VARCHAR(50) NOT NULL,
        source_id VARCHAR(100) NOT NULL,
        canonical_id VARCHAR(50) NOT NULL,
        match_type VARCHAR(50) NOT NULL,
        confidence_score DECIMAL(5,2) NULL,
        created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
        updated_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),

        CONSTRAINT UQ_source_mapping
            UNIQUE (source_system, source_id),

        CONSTRAINT FK_mapping_canonical
            FOREIGN KEY (canonical_id)
            REFERENCES dbo.canonical_entities(canonical_id),

        CONSTRAINT CK_mapping_match_type
            CHECK (match_type IN
                ('NEW_ENTITY', 'EXACT_EMAIL', 'EXACT_EMAIL_NORMALIZED', 'RULE_NAME_PHONE', 'MANUAL')),

        CONSTRAINT CK_mapping_confidence
            CHECK (
                confidence_score IS NULL OR
                confidence_score BETWEEN 0 AND 100
            )
    );
END
ELSE
BEGIN
    -- Non-destructive update of match_type column width and check constraint
    IF EXISTS (
        SELECT 1
        FROM sys.check_constraints
        WHERE name = 'CK_mapping_match_type'
          AND parent_object_id = OBJECT_ID('dbo.canonical_mappings')
    )
    BEGIN
        ALTER TABLE dbo.canonical_mappings DROP CONSTRAINT CK_mapping_match_type;
    END

    ALTER TABLE dbo.canonical_mappings ALTER COLUMN match_type VARCHAR(50) NOT NULL;

    ALTER TABLE dbo.canonical_mappings ADD CONSTRAINT CK_mapping_match_type
        CHECK (match_type IN
            ('NEW_ENTITY', 'EXACT_EMAIL', 'EXACT_EMAIL_NORMALIZED', 'RULE_NAME_PHONE', 'MANUAL'));
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_mapping_canonical_id' AND object_id = OBJECT_ID('dbo.canonical_mappings'))
BEGIN
    CREATE INDEX IX_mapping_canonical_id ON dbo.canonical_mappings(canonical_id);
END
GO


-- ============================================================================
-- 6. MAPPING HISTORY
-- Immutable audit log of canonical mapping changes, splits, and reassignments.
-- ============================================================================
IF OBJECT_ID('dbo.mapping_history', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.mapping_history (
        history_id BIGINT IDENTITY(1,1) PRIMARY KEY,
        source_system VARCHAR(50) NOT NULL,
        source_id VARCHAR(100) NOT NULL,
        old_canonical_id VARCHAR(50) NULL,
        new_canonical_id VARCHAR(50) NOT NULL,
        change_reason NVARCHAR(500) NOT NULL,
        changed_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
        run_id UNIQUEIDENTIFIER NOT NULL,

        CONSTRAINT FK_history_run
            FOREIGN KEY (run_id)
            REFERENCES dbo.pipeline_runs(run_id),

        CONSTRAINT FK_history_old
            FOREIGN KEY (old_canonical_id)
            REFERENCES dbo.canonical_entities(canonical_id),

        CONSTRAINT FK_history_new
            FOREIGN KEY (new_canonical_id)
            REFERENCES dbo.canonical_entities(canonical_id)
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_history_source' AND object_id = OBJECT_ID('dbo.mapping_history'))
BEGIN
    CREATE INDEX IX_history_source ON dbo.mapping_history(source_system, source_id);
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_history_run_id' AND object_id = OBJECT_ID('dbo.mapping_history'))
BEGIN
    CREATE INDEX IX_history_run_id ON dbo.mapping_history(run_id);
END
GO


-- ============================================================================
-- 7. UNRESOLVED MAPPINGS
-- Records that lack sufficient identity data to match or create an entity.
-- ============================================================================
IF OBJECT_ID('dbo.unresolved_mappings', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.unresolved_mappings (
        unresolved_id BIGINT IDENTITY(1,1) PRIMARY KEY,
        source_record_id BIGINT NOT NULL,
        run_id UNIQUEIDENTIFIER NOT NULL,
        reason VARCHAR(100) NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'OPEN',
        created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),

        CONSTRAINT FK_unresolved_source
            FOREIGN KEY (source_record_id)
            REFERENCES dbo.source_records(source_record_id),

        CONSTRAINT FK_unresolved_run
            FOREIGN KEY (run_id)
            REFERENCES dbo.pipeline_runs(run_id),

        CONSTRAINT CK_unresolved_status
            CHECK (status IN ('OPEN', 'RESOLVED', 'REJECTED'))
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_unresolved_run_id' AND object_id = OBJECT_ID('dbo.unresolved_mappings'))
BEGIN
    CREATE INDEX IX_unresolved_run_id ON dbo.unresolved_mappings(run_id);
END
GO


-- ============================================================================
-- 8. DATA QUALITY REJECTS
-- Ingested records rejected due to missing keys, malformed emails, etc.
-- ============================================================================
IF OBJECT_ID('dbo.data_quality_rejects', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.data_quality_rejects (
        reject_id BIGINT IDENTITY(1,1) PRIMARY KEY,
        source_record_id BIGINT NOT NULL,
        run_id UNIQUEIDENTIFIER NOT NULL,
        rejection_reason NVARCHAR(1000) NOT NULL,
        rejected_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),

        CONSTRAINT FK_reject_source
            FOREIGN KEY (source_record_id)
            REFERENCES dbo.source_records(source_record_id),

        CONSTRAINT FK_reject_run
            FOREIGN KEY (run_id)
            REFERENCES dbo.pipeline_runs(run_id)
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_rejects_run_id' AND object_id = OBJECT_ID('dbo.data_quality_rejects'))
BEGIN
    CREATE INDEX IX_rejects_run_id ON dbo.data_quality_rejects(run_id);
END
GO


-- ============================================================================
-- 9. MAPPING CONFLICTS
-- Ambiguous matches requiring manual review or deterministic collision handling.
-- ============================================================================
IF OBJECT_ID('dbo.mapping_conflicts', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.mapping_conflicts (
        conflict_id BIGINT IDENTITY(1,1) PRIMARY KEY,
        source_record_id BIGINT NOT NULL,
        run_id UNIQUEIDENTIFIER NOT NULL,
        conflict_type VARCHAR(50) NOT NULL,
        conflict_details NVARCHAR(2000) NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'OPEN',
        detected_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),

        CONSTRAINT FK_conflict_source
            FOREIGN KEY (source_record_id)
            REFERENCES dbo.source_records(source_record_id),

        CONSTRAINT FK_conflict_run
            FOREIGN KEY (run_id)
            REFERENCES dbo.pipeline_runs(run_id),

        CONSTRAINT CK_conflict_status
            CHECK (status IN ('OPEN', 'RESOLVED', 'DISMISSED'))
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_conflicts_status' AND object_id = OBJECT_ID('dbo.mapping_conflicts'))
BEGIN
    CREATE INDEX IX_conflicts_status ON dbo.mapping_conflicts(status);
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_conflicts_run_id' AND object_id = OBJECT_ID('dbo.mapping_conflicts'))
BEGIN
    CREATE INDEX IX_conflicts_run_id ON dbo.mapping_conflicts(run_id);
END
GO

PRINT 'Entity Resolution schema aligned and verified successfully!';
GO
