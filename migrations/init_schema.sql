-- OpenDoor Data Platform Database Schema
-- Initial schema creation for the Practice Knowledge Graph

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================================
-- PHYSICIANS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS physicians (
    npi VARCHAR(10) PRIMARY KEY,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    middle_name VARCHAR(100),
    name_suffix VARCHAR(20),
    credential VARCHAR(20),

    -- Specialty information
    specialty_primary VARCHAR(50),
    specialty_secondary VARCHAR(50),
    specialty_description VARCHAR(200),

    -- Demographics
    gender CHAR(1),
    graduation_year INTEGER,
    birth_year INTEGER,

    -- Practice location
    practice_address_line1 VARCHAR(200),
    practice_address_line2 VARCHAR(200),
    practice_city VARCHAR(100),
    practice_state CHAR(2),
    practice_zip VARCHAR(10),
    practice_phone VARCHAR(10),

    -- Administrative
    enumeration_date DATE,
    last_update_date DATE,
    is_sole_proprietor BOOLEAN DEFAULT FALSE,
    is_organization_subpart BOOLEAN DEFAULT FALSE,
    parent_organization_npi VARCHAR(10),

    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    data_source VARCHAR(50) DEFAULT 'nppes'
);

-- Indexes for physicians
CREATE INDEX IF NOT EXISTS idx_physicians_state ON physicians(practice_state);
CREATE INDEX IF NOT EXISTS idx_physicians_zip ON physicians(practice_zip);
CREATE INDEX IF NOT EXISTS idx_physicians_specialty ON physicians(specialty_primary);
CREATE INDEX IF NOT EXISTS idx_physicians_last_name ON physicians(last_name);
CREATE INDEX IF NOT EXISTS idx_physicians_sole_proprietor ON physicians(is_sole_proprietor);
CREATE INDEX IF NOT EXISTS idx_physicians_updated ON physicians(updated_at);

-- ============================================================================
-- PRACTICES TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS practices (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(300) NOT NULL,
    dba_name VARCHAR(300),
    practice_type VARCHAR(50) DEFAULT 'other',
    tax_id VARCHAR(12),
    organization_npi VARCHAR(10),

    -- Primary location
    address_line1 VARCHAR(200),
    address_line2 VARCHAR(200),
    city VARCHAR(100),
    state CHAR(2),
    zip_code VARCHAR(10),
    county VARCHAR(100),
    latitude DECIMAL(10, 7),
    longitude DECIMAL(10, 7),
    is_rural BOOLEAN DEFAULT FALSE,
    cbsa_code VARCHAR(10),

    -- Provider metrics
    physician_count INTEGER DEFAULT 1,
    provider_count INTEGER DEFAULT 1,

    -- Patient metrics
    patient_panel_size INTEGER,
    annual_patient_visits INTEGER,

    -- Financial metrics
    revenue_annual DECIMAL(15, 2),
    revenue_per_physician DECIMAL(15, 2),
    ebitda DECIMAL(15, 2),
    ebitda_margin DECIMAL(5, 4),
    operating_expenses DECIMAL(15, 2),

    -- Payer mix (percentages)
    payer_mix_medicare DECIMAL(5, 4) DEFAULT 0,
    payer_mix_medicaid DECIMAL(5, 4) DEFAULT 0,
    payer_mix_commercial DECIMAL(5, 4) DEFAULT 0,
    payer_mix_self_pay DECIMAL(5, 4) DEFAULT 0,
    payer_mix_other DECIMAL(5, 4) DEFAULT 0,

    -- Specialty
    specialty_primary VARCHAR(50),
    specialty_description VARCHAR(200),

    -- Administrative
    established_date DATE,
    last_verified_date TIMESTAMP WITH TIME ZONE,
    data_source VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,

    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for practices
CREATE INDEX IF NOT EXISTS idx_practices_state ON practices(state);
CREATE INDEX IF NOT EXISTS idx_practices_zip ON practices(zip_code);
CREATE INDEX IF NOT EXISTS idx_practices_specialty ON practices(specialty_primary);
CREATE INDEX IF NOT EXISTS idx_practices_type ON practices(practice_type);
CREATE INDEX IF NOT EXISTS idx_practices_org_npi ON practices(organization_npi);
CREATE INDEX IF NOT EXISTS idx_practices_active ON practices(is_active);

-- ============================================================================
-- PRACTICE_PHYSICIANS JUNCTION TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS practice_physicians (
    practice_id UUID REFERENCES practices(id) ON DELETE CASCADE,
    physician_npi VARCHAR(10) REFERENCES physicians(npi) ON DELETE CASCADE,
    is_owner BOOLEAN DEFAULT FALSE,
    is_primary BOOLEAN DEFAULT FALSE,
    start_date DATE,
    end_date DATE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (practice_id, physician_npi)
);

CREATE INDEX IF NOT EXISTS idx_practice_physicians_npi ON practice_physicians(physician_npi);

-- ============================================================================
-- PAYERS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS payers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(300) NOT NULL,
    payer_type VARCHAR(50) DEFAULT 'other',
    payer_id VARCHAR(50),
    parent_company VARCHAR(300),

    -- Geographic coverage
    states_active TEXT[],
    is_national BOOLEAN DEFAULT FALSE,

    -- Reimbursement characteristics
    average_reimbursement_rate DECIMAL(5, 3) DEFAULT 1.0,
    payment_timeliness_days INTEGER,
    denial_rate DECIMAL(5, 4),

    -- Market information
    market_share DECIMAL(5, 4),
    member_count INTEGER,

    -- Contact
    website VARCHAR(500),
    provider_services_phone VARCHAR(20),

    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_payers_type ON payers(payer_type);
CREATE INDEX IF NOT EXISTS idx_payers_name ON payers(name);

-- ============================================================================
-- PAYER_CONTRACTS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS payer_contracts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    payer_id UUID REFERENCES payers(id) ON DELETE CASCADE,
    practice_id UUID REFERENCES practices(id) ON DELETE CASCADE,
    contract_number VARCHAR(100),

    -- Contract status
    status VARCHAR(20) DEFAULT 'active',
    effective_date DATE NOT NULL,
    termination_date DATE,
    auto_renew BOOLEAN DEFAULT TRUE,

    -- Reimbursement terms
    fee_schedule_type VARCHAR(50) DEFAULT 'medicare_percentage',
    base_rate_multiplier DECIMAL(5, 3) DEFAULT 1.0,

    -- Rate schedule (JSONB for flexibility)
    rate_schedule JSONB,

    -- Additional terms
    value_based_component BOOLEAN DEFAULT FALSE,
    quality_bonus_eligible BOOLEAN DEFAULT FALSE,
    capitation_amount DECIMAL(10, 2),

    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_payer_contracts_payer ON payer_contracts(payer_id);
CREATE INDEX IF NOT EXISTS idx_payer_contracts_practice ON payer_contracts(practice_id);
CREATE INDEX IF NOT EXISTS idx_payer_contracts_status ON payer_contracts(status);

-- ============================================================================
-- VALUATIONS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS valuations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    practice_id UUID REFERENCES practices(id) ON DELETE CASCADE,
    calculation_timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Valuation amounts
    valuation_amount DECIMAL(15, 2) NOT NULL,
    valuation_low DECIMAL(15, 2),
    valuation_high DECIMAL(15, 2),

    -- Methodology
    method VARCHAR(50) NOT NULL,

    -- Multipliers
    payer_mix_multiplier DECIMAL(5, 3) DEFAULT 1.0,
    geographic_multiplier DECIMAL(5, 3) DEFAULT 1.0,
    specialty_multiplier DECIMAL(5, 3) DEFAULT 1.0,
    size_multiplier DECIMAL(5, 3) DEFAULT 1.0,
    growth_multiplier DECIMAL(5, 3) DEFAULT 1.0,
    quality_multiplier DECIMAL(5, 3) DEFAULT 1.0,
    risk_adjustment DECIMAL(5, 3) DEFAULT 1.0,
    combined_multiplier DECIMAL(6, 3),

    -- Multiplier rationales
    payer_mix_rationale TEXT,
    geographic_rationale TEXT,
    specialty_rationale TEXT,

    -- Basis values
    base_revenue DECIMAL(15, 2),
    base_ebitda DECIMAL(15, 2),
    patient_panel_size INTEGER,
    revenue_per_patient DECIMAL(10, 2),

    -- Implied multiples
    revenue_multiple DECIMAL(5, 2),
    ebitda_multiple DECIMAL(5, 2),

    -- Confidence metrics
    confidence_level VARCHAR(20) DEFAULT 'medium',
    data_completeness_score DECIMAL(5, 4) DEFAULT 0,
    assumptions JSONB,

    -- Additional components
    real_estate_value DECIMAL(15, 2),
    equipment_value DECIMAL(15, 2),
    goodwill_value DECIMAL(15, 2),

    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_valuations_practice ON valuations(practice_id);
CREATE INDEX IF NOT EXISTS idx_valuations_timestamp ON valuations(calculation_timestamp);
CREATE INDEX IF NOT EXISTS idx_valuations_confidence ON valuations(confidence_level);

-- ============================================================================
-- PHYSICIAN_SEGMENTS TABLE (for analytics)
-- ============================================================================
CREATE TABLE IF NOT EXISTS physician_segments (
    physician_npi VARCHAR(10) PRIMARY KEY REFERENCES physicians(npi) ON DELETE CASCADE,
    segment_type VARCHAR(20) NOT NULL,  -- type_1, type_2, type_3, type_4
    segment_score DECIMAL(5, 4),
    acquisition_likelihood DECIMAL(5, 4),

    -- Segment factors
    is_solo_owner BOOLEAN DEFAULT FALSE,
    is_declining_revenue BOOLEAN DEFAULT FALSE,
    is_near_retirement BOOLEAN DEFAULT FALSE,
    has_partnership_potential BOOLEAN DEFAULT FALSE,
    is_health_system_employed BOOLEAN DEFAULT FALSE,
    is_recent_graduate BOOLEAN DEFAULT FALSE,
    estimated_debt_level VARCHAR(20),

    -- Metadata
    segment_date TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_physician_segments_type ON physician_segments(segment_type);
CREATE INDEX IF NOT EXISTS idx_physician_segments_likelihood ON physician_segments(acquisition_likelihood);

-- ============================================================================
-- CMS_PAYMENTS TABLE (for Medicare payment data)
-- ============================================================================
CREATE TABLE IF NOT EXISTS cms_payments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    physician_npi VARCHAR(10) REFERENCES physicians(npi) ON DELETE CASCADE,
    year INTEGER NOT NULL,

    -- Payment metrics
    total_medicare_payment DECIMAL(15, 2),
    total_services INTEGER,
    total_beneficiaries INTEGER,

    -- Average metrics
    avg_submitted_charge DECIMAL(10, 2),
    avg_medicare_allowed DECIMAL(10, 2),
    avg_medicare_payment DECIMAL(10, 2),

    -- Service breakdown (JSONB for flexibility)
    service_breakdown JSONB,

    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    UNIQUE(physician_npi, year)
);

CREATE INDEX IF NOT EXISTS idx_cms_payments_npi ON cms_payments(physician_npi);
CREATE INDEX IF NOT EXISTS idx_cms_payments_year ON cms_payments(year);
CREATE INDEX IF NOT EXISTS idx_cms_payments_amount ON cms_payments(total_medicare_payment);

-- ============================================================================
-- AUDIT LOG TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS audit_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    table_name VARCHAR(100) NOT NULL,
    record_id VARCHAR(100) NOT NULL,
    action VARCHAR(20) NOT NULL,  -- INSERT, UPDATE, DELETE
    old_values JSONB,
    new_values JSONB,
    changed_by VARCHAR(100),
    changed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_log_table ON audit_log(table_name);
CREATE INDEX IF NOT EXISTS idx_audit_log_record ON audit_log(record_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log(changed_at);

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply update trigger to tables
DROP TRIGGER IF EXISTS update_physicians_updated_at ON physicians;
CREATE TRIGGER update_physicians_updated_at
    BEFORE UPDATE ON physicians
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_practices_updated_at ON practices;
CREATE TRIGGER update_practices_updated_at
    BEFORE UPDATE ON practices
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_payers_updated_at ON payers;
CREATE TRIGGER update_payers_updated_at
    BEFORE UPDATE ON payers
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_payer_contracts_updated_at ON payer_contracts;
CREATE TRIGGER update_payer_contracts_updated_at
    BEFORE UPDATE ON payer_contracts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_physician_segments_updated_at ON physician_segments;
CREATE TRIGGER update_physician_segments_updated_at
    BEFORE UPDATE ON physician_segments
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- COMMENTS
-- ============================================================================
COMMENT ON TABLE physicians IS 'Healthcare providers with NPI from NPPES';
COMMENT ON TABLE practices IS 'Healthcare practices and facilities';
COMMENT ON TABLE payers IS 'Insurance payers and government programs';
COMMENT ON TABLE valuations IS 'Practice valuation calculations';
COMMENT ON TABLE physician_segments IS 'Physician acquisition target segments';
COMMENT ON TABLE cms_payments IS 'Medicare payment data from CMS';
