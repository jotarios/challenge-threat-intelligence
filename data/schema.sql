-- Threat Intelligence Database Schema

-- Threat Actors
CREATE TABLE threat_actors (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    country_origin TEXT,
    first_seen TIMESTAMP,
    last_seen TIMESTAMP,
    sophistication_level TEXT CHECK(sophistication_level IN ('low', 'medium', 'high', 'advanced')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Campaigns
CREATE TABLE campaigns (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    first_seen TIMESTAMP,
    last_seen TIMESTAMP,
    status TEXT CHECK(status IN ('active', 'dormant', 'completed')),
    target_sectors TEXT, -- comma-separated
    target_regions TEXT, -- comma-separated
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indicators
CREATE TABLE indicators (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL CHECK(type IN ('ip', 'domain', 'url', 'hash')),
    value TEXT NOT NULL,
    confidence INTEGER CHECK(confidence BETWEEN 0 AND 100),
    first_seen TIMESTAMP,
    last_seen TIMESTAMP,
    tags TEXT, -- comma-separated tags
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(type, value)
);

-- Threat Actor <-> Campaign relationships
CREATE TABLE actor_campaigns (
    threat_actor_id TEXT,
    campaign_id TEXT,
    confidence INTEGER CHECK(confidence BETWEEN 0 AND 100),
    PRIMARY KEY (threat_actor_id, campaign_id),
    FOREIGN KEY (threat_actor_id) REFERENCES threat_actors(id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
);

-- Campaign <-> Indicator relationships
CREATE TABLE campaign_indicators (
    campaign_id TEXT,
    indicator_id TEXT,
    observed_at TIMESTAMP,
    PRIMARY KEY (campaign_id, indicator_id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id),
    FOREIGN KEY (indicator_id) REFERENCES indicators(id)
);

-- Indicator relationships (indicators related to each other)
CREATE TABLE indicator_relationships (
    source_indicator_id TEXT,
    target_indicator_id TEXT,
    relationship_type TEXT, -- 'same_campaign', 'same_infrastructure', 'co_occurring'
    confidence INTEGER CHECK(confidence BETWEEN 0 AND 100),
    first_observed TIMESTAMP,
    PRIMARY KEY (source_indicator_id, target_indicator_id, relationship_type),
    FOREIGN KEY (source_indicator_id) REFERENCES indicators(id),
    FOREIGN KEY (target_indicator_id) REFERENCES indicators(id)
);

-- Observations (when/where indicator was seen)
CREATE TABLE observations (
    id TEXT PRIMARY KEY,
    indicator_id TEXT,
    observed_at TIMESTAMP,
    source TEXT, -- e.g., 'honeypot', 'sandbox', 'customer_report'
    notes TEXT,
    FOREIGN KEY (indicator_id) REFERENCES indicators(id)
);

-- Indexes for common queries
CREATE INDEX idx_indicators_type ON indicators(type);
CREATE INDEX idx_indicators_value ON indicators(value);
CREATE INDEX idx_indicators_first_seen ON indicators(first_seen);
CREATE INDEX idx_indicators_last_seen ON indicators(last_seen);
CREATE INDEX idx_campaign_indicators_campaign ON campaign_indicators(campaign_id);
CREATE INDEX idx_campaign_indicators_indicator ON campaign_indicators(indicator_id);
CREATE INDEX idx_observations_indicator ON observations(indicator_id);
CREATE INDEX idx_observations_timestamp ON observations(observed_at);
CREATE INDEX idx_actor_campaigns_actor ON actor_campaigns(threat_actor_id);
CREATE INDEX idx_actor_campaigns_campaign ON actor_campaigns(campaign_id);
