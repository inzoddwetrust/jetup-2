#!/bin/bash

# ==============================================================================
# Jetup Bots Installation Script
# Installs both bots with PostgreSQL database
# ==============================================================================

# Configuration
INSTALL_BASE="/opt/jetup"
# Repository URLs will be set in setup_ssh function after configuring SSH aliases
BOT_REPO=""
HELPBOT_REPO=""

# PostgreSQL configuration
PG_DB="jetup2"
PG_USER="jetup"
PG_HELPBOT_USER="jetup_helpbot_reader"
PG_PASSWORD=""  # Will be generated

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Logging
log() { echo -e "${GREEN}[$(date +'%H:%M:%S')]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }
info() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}✓${NC} $1"; }

# Error handler
handle_error() {
    error "Error occurred at line: ${1}"
    exit 1
}
trap 'handle_error ${LINENO}' ERR

# Check root
if [ "$EUID" -ne 0 ]; then
    error "Please run as root"
    exit 1
fi

# ==============================================================================
# PRE-FLIGHT CHECKS
# ==============================================================================

preflight_checks() {
    log "Running pre-flight checks..."

    # Check Python version (need 3.10+)
    if command -v python3 &> /dev/null; then
        PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
        PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
        PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

        if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 10 ]; }; then
            warn "Python $PYTHON_VERSION detected, but 3.10+ required"
            info "Will install Python 3.10+ from deadsnakes PPA"
        else
            success "Python $PYTHON_VERSION OK"
        fi
    fi

    # Check disk space (need at least 5GB)
    AVAILABLE_SPACE=$(df /opt | tail -1 | awk '{print $4}')
    REQUIRED_SPACE=$((5 * 1024 * 1024))  # 5GB in KB

    if [ "$AVAILABLE_SPACE" -lt "$REQUIRED_SPACE" ]; then
        error "Insufficient disk space"
        error "Available: $(($AVAILABLE_SPACE / 1024 / 1024))GB, Required: 5GB"
        exit 1
    else
        success "Disk space OK ($(($AVAILABLE_SPACE / 1024 / 1024))GB available)"
    fi

    # Check if PostgreSQL 14+ will be available
    DEBIAN_VERSION=$(cat /etc/debian_version 2>/dev/null | cut -d. -f1)
    if [ -n "$DEBIAN_VERSION" ] && [ "$DEBIAN_VERSION" -lt 12 ]; then
        warn "Debian $DEBIAN_VERSION detected - may need PostgreSQL repo for version 14+"
    fi

    success "Pre-flight checks passed"
}

clear
echo -e "${CYAN}╔═══════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║         Jetup Bots Installation Script         ║${NC}"
echo -e "${CYAN}╚═══════════════════════════════════════════════╝${NC}"
echo ""

# Run pre-flight checks
preflight_checks
echo ""

# Check for previous installation
if [ -d "$INSTALL_BASE" ]; then
    warn "Found existing installation at $INSTALL_BASE"
    echo ""
    read -p "Remove existing installation and start fresh? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        log "Removing existing installation..."
        systemctl stop jetup-bot jetup-helpbot 2>/dev/null || true
        systemctl disable jetup-bot jetup-helpbot 2>/dev/null || true
        rm -rf "$INSTALL_BASE"
        rm -f /etc/systemd/system/jetup-*.service
        rm -f /usr/local/bin/jetup
        systemctl daemon-reload
        success "Previous installation removed"
    else
        error "Cannot proceed with existing installation"
        error "Please backup and remove $INSTALL_BASE manually"
        exit 1
    fi
fi

# ==============================================================================
# FIX LOCALE ISSUES
# ==============================================================================

fix_locale() {
    log "Fixing locale settings..."

    # Install locales package
    apt-get update
    apt-get install -y locales

    # Generate locales
    locale-gen en_US.UTF-8
    locale-gen ru_RU.UTF-8

    # Update locale
    update-locale LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8

    # Export for current session
    export LANG=en_US.UTF-8
    export LC_ALL=en_US.UTF-8
    export LC_CTYPE=en_US.UTF-8
    export LANGUAGE=en_US.UTF-8

    # Also set for Perl
    export LC_ALL=C

    success "Locale settings fixed"
}

# ==============================================================================
# SYSTEM DEPENDENCIES
# ==============================================================================

# Fix locale first
fix_locale

log "Installing system dependencies..."

apt-get update
apt-get install -y \
    python3 python3-venv python3-dev python3-pip \
    build-essential \
    git curl wget \
    openssh-client \
    postgresql postgresql-contrib \
    wkhtmltopdf \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    shared-mime-info

success "System dependencies installed (including PDF generation libraries)"

# ==============================================================================
# POSTGRESQL SETUP
# ==============================================================================

setup_postgresql() {
    log "Setting up PostgreSQL database..."

    # Generate secure password
    PG_PASSWORD=$(openssl rand -base64 32 | tr -d "=+/" | cut -c1-25)
    local PG_HELPBOT_PASSWORD=$(openssl rand -base64 32 | tr -d "=+/" | cut -c1-25)

    # Start PostgreSQL
    systemctl start postgresql
    systemctl enable postgresql

    # Create database and users
    sudo -u postgres psql << EOF
-- Drop if exists (for clean reinstall)
DROP DATABASE IF EXISTS $PG_DB;
DROP USER IF EXISTS $PG_USER;
DROP USER IF EXISTS $PG_HELPBOT_USER;

-- Create main user
CREATE USER $PG_USER WITH PASSWORD '$PG_PASSWORD';

-- Create read-only user for helpbot
CREATE USER $PG_HELPBOT_USER WITH PASSWORD '$PG_HELPBOT_PASSWORD';

-- Create database
CREATE DATABASE $PG_DB OWNER $PG_USER;

-- Connect to database and set permissions
\c $PG_DB

-- Grant all to main user
GRANT ALL PRIVILEGES ON DATABASE $PG_DB TO $PG_USER;
GRANT ALL PRIVILEGES ON SCHEMA public TO $PG_USER;
ALTER DEFAULT PRIVILEGES FOR USER $PG_USER IN SCHEMA public GRANT ALL ON TABLES TO $PG_USER;
ALTER DEFAULT PRIVILEGES FOR USER $PG_USER IN SCHEMA public GRANT ALL ON SEQUENCES TO $PG_USER;

-- Grant read-only to helpbot user
GRANT CONNECT ON DATABASE $PG_DB TO $PG_HELPBOT_USER;
GRANT USAGE ON SCHEMA public TO $PG_HELPBOT_USER;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO $PG_HELPBOT_USER;
ALTER DEFAULT PRIVILEGES FOR USER $PG_USER IN SCHEMA public GRANT SELECT ON TABLES TO $PG_HELPBOT_USER;

-- Ensure helpbot can read future tables
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO $PG_HELPBOT_USER;
EOF

    # Save credentials to file
    mkdir -p "$INSTALL_BASE/shared/creds"
    cat > "$INSTALL_BASE/shared/creds/postgres_credentials.txt" << EOF
PostgreSQL Credentials
======================

Main Bot User:
--------------
Database: $PG_DB
User: $PG_USER
Password: $PG_PASSWORD
Connection String: postgresql://$PG_USER:$PG_PASSWORD@localhost:5432/$PG_DB

Helpbot Read-Only User:
------------------------
Database: $PG_DB
User: $PG_HELPBOT_USER
Password: $PG_HELPBOT_PASSWORD
Connection String: postgresql://$PG_HELPBOT_USER:$PG_HELPBOT_PASSWORD@localhost:5432/$PG_DB

Generated: $(date)
EOF

    chmod 600 "$INSTALL_BASE/shared/creds/postgres_credentials.txt"

    success "PostgreSQL configured"
    info "Credentials saved to: $INSTALL_BASE/shared/creds/postgres_credentials.txt"
}

# ==============================================================================
# SSH SETUP
# ==============================================================================

setup_ssh() {
    log "Setting up SSH configuration for repositories..."

    # Add GitHub to known hosts
    if ! grep -q "github.com" ~/.ssh/known_hosts 2>/dev/null; then
        log "Adding GitHub to known hosts..."
        mkdir -p ~/.ssh
        chmod 700 ~/.ssh
        ssh-keyscan -H github.com >> ~/.ssh/known_hosts 2>/dev/null
    fi

    # Setup separate keys for each repository
    BOT_KEY=~/.ssh/id_ed25519_jetup_bot
    HELPBOT_KEY=~/.ssh/id_ed25519_jetup_helpbot

    local need_keys=false

    # Check for bot key
    if [ ! -f "$BOT_KEY" ]; then
        warn "No SSH key for jetup-2 repository"
        need_keys=true
    fi

    # Check for helpbot key
    if [ ! -f "$HELPBOT_KEY" ]; then
        warn "No SSH key for helpbot-2 repository"
        need_keys=true
    fi

    if [ "$need_keys" = true ]; then
        echo ""
        info "GitHub requires separate deploy keys for each repository."
        echo ""
        read -p "Generate SSH keys for both repositories? (y/n): " -n 1 -r
        echo

        if [[ $REPLY =~ ^[Yy]$ ]]; then
            # Generate key for main bot
            if [ ! -f "$BOT_KEY" ]; then
                log "Generating key for jetup-2..."
                ssh-keygen -t ed25519 -C "jetup-2-deploy" -f "$BOT_KEY" -N ""
                chmod 600 "$BOT_KEY"
                chmod 644 "${BOT_KEY}.pub"
            fi

            # Generate key for helpbot
            if [ ! -f "$HELPBOT_KEY" ]; then
                log "Generating key for helpbot-2..."
                ssh-keygen -t ed25519 -C "helpbot-2-deploy" -f "$HELPBOT_KEY" -N ""
                chmod 600 "$HELPBOT_KEY"
                chmod 644 "${HELPBOT_KEY}.pub"
            fi

            echo ""
            echo -e "${CYAN}═══════════════════════════════════════════════${NC}"
            echo -e "${CYAN}  Deploy Keys for GitHub Repositories${NC}"
            echo -e "${CYAN}═══════════════════════════════════════════════${NC}"
            echo ""
            echo -e "${YELLOW}1. For jetup-2 repository (main bot):${NC}"
            echo "   Go to: https://github.com/inzoddwetrust/jetup-2/settings/keys"
            echo "   Add this key:"
            echo ""
            cat "${BOT_KEY}.pub"
            echo ""
            echo -e "${YELLOW}2. For helpbot-2 repository:${NC}"
            echo "   Go to: https://github.com/inzoddwetrust/helpbot-2/settings/keys"
            echo "   Add this key:"
            echo ""
            cat "${HELPBOT_KEY}.pub"
            echo ""
            echo -e "${CYAN}═══════════════════════════════════════════════${NC}"
            echo ""
            read -p "Press Enter after adding BOTH keys to GitHub..."
        else
            error "SSH keys required for GitHub access"
            exit 1
        fi
    fi

    # Configure SSH config
    log "Configuring SSH..."

    # Backup existing config
    if [ -f ~/.ssh/config ]; then
        cp ~/.ssh/config ~/.ssh/config.backup
    fi

    # Add/update SSH config
    if ! grep -q "Host github.com-jetup-bot" ~/.ssh/config 2>/dev/null; then
        cat >> ~/.ssh/config << EOF

# Jetup Bot Repository
Host github.com-jetup-bot
    HostName github.com
    User git
    IdentityFile $BOT_KEY
    IdentitiesOnly yes

# Jetup Helpbot Repository
Host github.com-jetup-helpbot
    HostName github.com
    User git
    IdentityFile $HELPBOT_KEY
    IdentitiesOnly yes
EOF
        chmod 600 ~/.ssh/config
    fi

    # Update repository URLs to use SSH aliases
    BOT_REPO="git@github.com-jetup-bot:inzoddwetrust/jetup-2.git"
    HELPBOT_REPO="git@github.com-jetup-helpbot:inzoddwetrust/helpbot-2.git"

    # Test connections
    log "Testing GitHub connections..."

    if ssh -T git@github.com-jetup-bot 2>&1 | grep -q "successfully authenticated"; then
        success "✓ jetup-2 repository accessible"
    else
        error "Cannot connect to jetup-2 repository"
        error "Make sure the key is added to: https://github.com/inzoddwetrust/jetup-2/settings/keys"
        return 1
    fi

    if ssh -T git@github.com-jetup-helpbot 2>&1 | grep -q "successfully authenticated"; then
        success "✓ helpbot-2 repository accessible"
    else
        error "Cannot connect to helpbot-2 repository"
        error "Make sure the key is added to: https://github.com/inzoddwetrust/helpbot-2/settings/keys"
        return 1
    fi

    success "SSH configuration complete"
}

# ==============================================================================
# DIRECTORY STRUCTURE
# ==============================================================================

create_directory_structure() {
    log "Creating directory structure..."

    # Main directories
    mkdir -p "$INSTALL_BASE"/{bot,helpbot,shared,scripts,backups}
    mkdir -p "$INSTALL_BASE"/bot/{app,data,venv}
    mkdir -p "$INSTALL_BASE"/helpbot/{app,data,venv}
    mkdir -p "$INSTALL_BASE"/shared/{creds,logs,temp}
    mkdir -p "$INSTALL_BASE"/backups/{daily,weekly,monthly,import}

    success "Directory structure created"
}

# ==============================================================================
# BOT INSTALLATION
# ==============================================================================

install_bot() {
    local NAME=$1
    local REPO=$2
    local INSTALL_DIR=$3
    local SERVICE_NAME=$4
    local ENTRY_POINT=$5

    log "Installing $NAME..."

    # Clone repository
    log "Cloning repository..."
    git clone "$REPO" "$INSTALL_DIR/app" || {
        error "Failed to clone $NAME repository"
        error "Check that deploy key is added and has correct permissions"
        return 1
    }

    # Create virtual environment
    log "Creating Python virtual environment..."
    python3 -m venv "$INSTALL_DIR/venv"

    # Install dependencies
    log "Installing Python dependencies..."
    source "$INSTALL_DIR/venv/bin/activate"
    pip install --upgrade pip

    # Install from requirements
    if [ -f "$INSTALL_DIR/app/requirements.txt" ]; then
        pip install -r "$INSTALL_DIR/app/requirements.txt"
    fi

    # Add psycopg2-binary for PostgreSQL
    pip install psycopg2-binary

    deactivate

    # Create .env template if doesn't exist
    if [ ! -f "$INSTALL_DIR/app/.env" ]; then
        log "Creating .env template..."

        if [ "$SERVICE_NAME" = "jetup-bot" ]; then
            cat > "$INSTALL_DIR/app/.env" << EOF
# Bot credentials
API_TOKEN=YOUR_BOT_TOKEN_HERE
ADMINS=YOUR_ADMIN_IDS_HERE

# Database URL (PostgreSQL)
DATABASE_URL=postgresql://$PG_USER:$PG_PASSWORD@localhost:5432/$PG_DB

# Other settings
LOG_LEVEL=INFO
EOF
        else
            # Helpbot uses read-only connection
            cat > "$INSTALL_DIR/app/.env" << EOF
# Bot credentials
API_TOKEN=YOUR_BOT_TOKEN_HERE
ADMINS=YOUR_ADMIN_IDS_HERE

# Helpbot database (SQLite)
DATABASE_URL=sqlite:///../data/helpbot.db

# Mainbot database (PostgreSQL - READ ONLY)
MAINBOT_DATABASE_URL=postgresql://$PG_HELPBOT_USER:$PG_HELPBOT_PASSWORD@localhost:5432/$PG_DB

# Google Sheets
GOOGLE_SHEET_ID=YOUR_GOOGLE_SHEET_ID_HERE
GOOGLE_CREDENTIALS_JSON=../../shared/creds/helpbot_key.json

# Helpbot specific
HELPBOT_GROUP_ID=YOUR_GROUP_ID_HERE
EOF
        fi

        chmod 600 "$INSTALL_DIR/app/.env"
    fi

    # Create systemd service
    log "Creating systemd service..."
    cat > "/etc/systemd/system/$SERVICE_NAME.service" << EOF
[Unit]
Description=$NAME
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR/app
Environment="PATH=$INSTALL_DIR/venv/bin"
ExecStart=$INSTALL_DIR/venv/bin/python $INSTALL_DIR/app/$ENTRY_POINT
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

# Resource limits
LimitNOFILE=65536
MemoryLimit=2G
CPUQuota=200%

# Security hardening
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload

    success "$NAME installed"
}

# ==============================================================================
# MANAGEMENT SCRIPT
# ==============================================================================

create_management_script() {
    log "Creating management script..."

    cat > "$INSTALL_BASE/scripts/manage.sh" << 'EOF'
#!/bin/bash

INSTALL_BASE="/opt/jetup"

case "${1:-}" in
    start)
        case "${2:-all}" in
            bot)
                echo "Starting Jetup bot..."
                systemctl start jetup-bot
                ;;
            helpbot)
                echo "Starting Jetup helpbot..."
                systemctl start jetup-helpbot
                ;;
            all|"")
                echo "Starting all services..."
                systemctl start jetup-bot jetup-helpbot
                ;;
            *)
                echo "Usage: $0 start [bot|helpbot|all]"
                exit 1
                ;;
        esac
        ;;

    stop)
        case "${2:-all}" in
            bot)
                echo "Stopping Jetup bot..."
                systemctl stop jetup-bot
                ;;
            helpbot)
                echo "Stopping Jetup helpbot..."
                systemctl stop jetup-helpbot
                ;;
            all|"")
                echo "Stopping all services..."
                systemctl stop jetup-bot jetup-helpbot
                ;;
            *)
                echo "Usage: $0 stop [bot|helpbot|all]"
                exit 1
                ;;
        esac
        ;;

    restart)
        case "${2:-all}" in
            bot)
                echo "Restarting Jetup bot..."
                systemctl restart jetup-bot
                ;;
            helpbot)
                echo "Restarting Jetup helpbot..."
                systemctl restart jetup-helpbot
                ;;
            all|"")
                echo "Restarting all services..."
                systemctl restart jetup-bot jetup-helpbot
                ;;
            *)
                echo "Usage: $0 restart [bot|helpbot|all]"
                exit 1
                ;;
        esac
        ;;

    status)
        echo "=== Jetup Services Status ==="
        echo ""
        echo "Main Bot:"
        systemctl status jetup-bot --no-pager -l
        echo ""
        echo "Helpbot:"
        systemctl status jetup-helpbot --no-pager -l
        ;;

    logs)
        case "${2:-both}" in
            bot)
                journalctl -u jetup-bot -f
                ;;
            helpbot)
                journalctl -u jetup-helpbot -f
                ;;
            both|"")
                journalctl -u jetup-bot -u jetup-helpbot -f
                ;;
            *)
                echo "Usage: $0 logs [bot|helpbot|both]"
                exit 1
                ;;
        esac
        ;;

    update)
        case "${2:-all}" in
            bot)
                echo "Updating Jetup bot..."
                cd "$INSTALL_BASE/bot/app"

                # Save current branch and status
                BRANCH=$(git branch --show-current)
                echo "Current branch: $BRANCH"

                # Check for uncommitted changes
                if ! git diff-index --quiet HEAD --; then
                    echo "⚠ WARNING: Uncommitted changes detected!"
                    git status --short
                    read -p "Continue anyway? (y/n): " -n 1 -r
                    echo
                    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                        echo "Update cancelled"
                        exit 1
                    fi
                fi

                # Create backup before update
                TIMESTAMP=$(date +%Y%m%d_%H%M%S)
                BACKUP_DIR="/tmp/jetup_update_backup_${TIMESTAMP}"
                mkdir -p "$BACKUP_DIR"

                echo "Creating backup before update..."
                git status > "$BACKUP_DIR/git_status.txt" 2>/dev/null || true
                git diff > "$BACKUP_DIR/git_diff.txt" 2>/dev/null || true
                cp .env "$BACKUP_DIR/.env" 2>/dev/null || true
                echo "Backup created at: $BACKUP_DIR"

                # Fetch and check for updates
                git fetch origin
                if git diff --quiet HEAD origin/$BRANCH; then
                    echo "✓ Already up to date"
                    exit 0
                fi

                # Pull updates with conflict resolution
                echo "Pulling updates..."

                # Try to pull with rebase first
                if git pull --rebase origin "$BRANCH" 2>/dev/null; then
                    echo "✓ Updates pulled successfully"
                elif git pull --ff-only origin "$BRANCH" 2>/dev/null; then
                    echo "✓ Updates pulled (fast-forward)"
                else
                    echo "❌ Cannot pull - conflicts detected or diverged branches"
                    echo ""
                    echo "Options:"
                    echo "  1) Discard local changes (reset --hard)"
                    echo "  2) Stash local changes and try again"
                    echo "  3) Cancel update"
                    echo ""
                    read -p "Choose option [1-3]: " -n 1 -r
                    echo

                    case $REPLY in
                        1)
                            echo "Discarding local changes..."
                            git reset --hard origin/$BRANCH
                            echo "✓ Reset to origin/$BRANCH"
                            ;;
                        2)
                            echo "Stashing local changes..."
                            git stash save "Auto-stash before update $(date)"
                            git pull origin "$BRANCH"
                            echo "Attempting to restore stashed changes..."
                            if git stash pop; then
                                echo "✓ Stash restored successfully"
                            else
                                echo "⚠ Conflicts when restoring stash"
                                echo "Resolve manually and run: git stash drop"
                            fi
                            ;;
                        3|*)
                            echo "Update cancelled"
                            echo "Backup available at: $BACKUP_DIR"
                            exit 1
                            ;;
                    esac
                fi

                # Update dependencies if needed
                if [ -f "requirements.txt" ]; then
                    echo "Updating dependencies..."
                    source "$INSTALL_BASE/bot/venv/bin/activate"
                    pip install -r requirements.txt
                    deactivate
                fi

                echo "✓ Bot updated successfully"
                echo "Run 'jetup restart bot' to apply changes"
                ;;

            helpbot)
                echo "Updating Jetup helpbot..."
                cd "$INSTALL_BASE/helpbot/app"

                # Save current branch and status
                BRANCH=$(git branch --show-current)
                echo "Current branch: $BRANCH"

                # Check for uncommitted changes
                if ! git diff-index --quiet HEAD --; then
                    echo "⚠ WARNING: Uncommitted changes detected!"
                    git status --short
                    read -p "Continue anyway? (y/n): " -n 1 -r
                    echo
                    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                        echo "Update cancelled"
                        exit 1
                    fi
                fi

                # Create backup before update
                TIMESTAMP=$(date +%Y%m%d_%H%M%S)
                BACKUP_DIR="/tmp/jetup_update_backup_${TIMESTAMP}"
                mkdir -p "$BACKUP_DIR"

                echo "Creating backup before update..."
                git status > "$BACKUP_DIR/git_status.txt" 2>/dev/null || true
                git diff > "$BACKUP_DIR/git_diff.txt" 2>/dev/null || true
                cp .env "$BACKUP_DIR/.env" 2>/dev/null || true
                echo "Backup created at: $BACKUP_DIR"

                # Fetch and check for updates
                git fetch origin
                if git diff --quiet HEAD origin/$BRANCH; then
                    echo "✓ Already up to date"
                    exit 0
                fi

                # Pull updates with conflict resolution
                echo "Pulling updates..."

                # Try to pull with rebase first
                if git pull --rebase origin "$BRANCH" 2>/dev/null; then
                    echo "✓ Updates pulled successfully"
                elif git pull --ff-only origin "$BRANCH" 2>/dev/null; then
                    echo "✓ Updates pulled (fast-forward)"
                else
                    echo "❌ Cannot pull - conflicts detected or diverged branches"
                    echo ""
                    echo "Options:"
                    echo "  1) Discard local changes (reset --hard)"
                    echo "  2) Stash local changes and try again"
                    echo "  3) Cancel update"
                    echo ""
                    read -p "Choose option [1-3]: " -n 1 -r
                    echo

                    case $REPLY in
                        1)
                            echo "Discarding local changes..."
                            git reset --hard origin/$BRANCH
                            echo "✓ Reset to origin/$BRANCH"
                            ;;
                        2)
                            echo "Stashing local changes..."
                            git stash save "Auto-stash before update $(date)"
                            git pull origin "$BRANCH"
                            echo "Attempting to restore stashed changes..."
                            if git stash pop; then
                                echo "✓ Stash restored successfully"
                            else
                                echo "⚠ Conflicts when restoring stash"
                                echo "Resolve manually and run: git stash drop"
                            fi
                            ;;
                        3|*)
                            echo "Update cancelled"
                            echo "Backup available at: $BACKUP_DIR"
                            exit 1
                            ;;
                    esac
                fi

                # Update dependencies if needed
                if [ -f "requirements.txt" ]; then
                    echo "Updating dependencies..."
                    source "$INSTALL_BASE/helpbot/venv/bin/activate"
                    pip install -r requirements.txt
                    deactivate
                fi

                echo "✓ Helpbot updated successfully"
                echo "Run 'jetup restart helpbot' to apply changes"
                ;;

            all|"")
                echo "Updating all repositories..."

                # Update bot
                echo ""
                echo "=== Updating Main Bot ==="
                cd "$INSTALL_BASE/bot/app"
                BRANCH=$(git branch --show-current)

                if ! git diff-index --quiet HEAD --; then
                    echo "⚠ Bot has uncommitted changes"
                    git status --short
                fi

                git fetch origin
                if ! git diff --quiet HEAD origin/$BRANCH; then
                    echo "Pulling bot updates..."
                    git pull origin "$BRANCH"
                    if [ -f "requirements.txt" ]; then
                        source "$INSTALL_BASE/bot/venv/bin/activate"
                        pip install -r requirements.txt
                        deactivate
                    fi
                else
                    echo "✓ Bot already up to date"
                fi

                # Update helpbot
                echo ""
                echo "=== Updating Helpbot ==="
                cd "$INSTALL_BASE/helpbot/app"
                BRANCH=$(git branch --show-current)

                if ! git diff-index --quiet HEAD --; then
                    echo "⚠ Helpbot has uncommitted changes"
                    git status --short
                fi

                git fetch origin
                if ! git diff --quiet HEAD origin/$BRANCH; then
                    echo "Pulling helpbot updates..."
                    git pull origin "$BRANCH"
                    if [ -f "requirements.txt" ]; then
                        source "$INSTALL_BASE/helpbot/venv/bin/activate"
                        pip install -r requirements.txt
                        deactivate
                    fi
                else
                    echo "✓ Helpbot already up to date"
                fi

                echo ""
                echo "✓ All repositories updated"
                echo "Run 'jetup restart' to apply changes"
                ;;

            *)
                echo "Usage: $0 update [bot|helpbot|all]"
                exit 1
                ;;
        esac
        ;;

    backup)
        TIMESTAMP=$(date +%Y%m%d_%H%M%S)
        BACKUP_DIR="$INSTALL_BASE/backups/daily/backup_$TIMESTAMP"
        mkdir -p "$BACKUP_DIR"

        echo "Creating backup..."

        # Backup PostgreSQL database
        sudo -u postgres pg_dump jetup2 > "$BACKUP_DIR/jetup2.sql"

        # Backup helpbot SQLite database
        cp "$INSTALL_BASE"/helpbot/data/*.db "$BACKUP_DIR/" 2>/dev/null || true

        # Backup configs
        cp "$INSTALL_BASE"/bot/app/.env "$BACKUP_DIR/bot.env" 2>/dev/null || true
        cp "$INSTALL_BASE"/helpbot/app/.env "$BACKUP_DIR/helpbot.env" 2>/dev/null || true

        # Backup credentials
        cp -r "$INSTALL_BASE/shared/creds" "$BACKUP_DIR/" 2>/dev/null || true

        # Create archive
        cd "$INSTALL_BASE/backups/daily"
        tar -czf "backup_$TIMESTAMP.tar.gz" "backup_$TIMESTAMP"
        rm -rf "backup_$TIMESTAMP"

        echo "✓ Backup created: $INSTALL_BASE/backups/daily/backup_$TIMESTAMP.tar.gz"

        # Rotate old backups
        echo "Rotating old backups..."
        find "$INSTALL_BASE/backups/daily" -name "backup_*.tar.gz" -mtime +7 -delete
        find "$INSTALL_BASE/backups/weekly" -name "backup_*.tar.gz" -mtime +30 -delete 2>/dev/null || true
        find "$INSTALL_BASE/backups/monthly" -name "backup_*.tar.gz" -mtime +365 -delete 2>/dev/null || true

        DAILY_COUNT=$(find "$INSTALL_BASE/backups/daily" -name "backup_*.tar.gz" | wc -l)
        echo "✓ Rotation complete. Kept last 7 days ($DAILY_COUNT backups)"
        ;;

    db)
        case "${2:-}" in
            connect)
                echo "Connecting to PostgreSQL..."
                sudo -u postgres psql jetup2
                ;;
            dump)
                TIMESTAMP=$(date +%Y%m%d_%H%M%S)
                OUTPUT="$INSTALL_BASE/backups/db_dump_$TIMESTAMP.sql"
                echo "Dumping database to $OUTPUT..."
                sudo -u postgres pg_dump jetup2 > "$OUTPUT"
                echo "✓ Database dumped"
                ;;
            restore)
                if [ -z "${3:-}" ]; then
                    echo "Usage: $0 db restore <dump_file>"
                    exit 1
                fi
                echo "Restoring database from $3..."
                sudo -u postgres psql jetup2 < "$3"
                echo "✓ Database restored"
                ;;
            *)
                echo "Database commands:"
                echo "  $0 db connect        - Connect to PostgreSQL"
                echo "  $0 db dump           - Create database dump"
                echo "  $0 db restore <file> - Restore from dump"
                ;;
        esac
        ;;

    version)
        echo "Jetup Management System v1.0"
        echo ""
        echo "Checking versions..."
        cd "$INSTALL_BASE/bot/app" 2>/dev/null && {
            echo -n "Main bot: "
            git describe --tags --always 2>/dev/null || git rev-parse --short HEAD 2>/dev/null || echo "unknown"
        }
        cd "$INSTALL_BASE/helpbot/app" 2>/dev/null && {
            echo -n "Helpbot: "
            git describe --tags --always 2>/dev/null || git rev-parse --short HEAD 2>/dev/null || echo "unknown"
        }
        ;;

    *)
        echo "Jetup Management System"
        echo "Usage: $0 {command} [options]"
        echo ""
        echo "Service Management:"
        echo "  start [bot|helpbot]    - Start service(s)"
        echo "  stop [bot|helpbot]     - Stop service(s)"
        echo "  restart [bot|helpbot]  - Restart service(s)"
        echo "  status                 - Show service status"
        echo ""
        echo "Maintenance:"
        echo "  update [bot|helpbot]   - Update from GitHub"
        echo "  logs [bot|helpbot|both]- View logs"
        echo "  backup                 - Create backup"
        echo "  version                - Show versions"
        echo ""
        echo "Database:"
        echo "  db connect             - Connect to PostgreSQL"
        echo "  db dump                - Create database dump"
        echo "  db restore <file>      - Restore database"
        echo ""
        echo "Examples:"
        echo "  jetup update bot       - Update only main bot"
        echo "  jetup restart all      - Restart all services"
        echo "  jetup logs both        - Show combined logs"
        echo "  jetup db dump          - Backup database"
        ;;
esac
EOF

    chmod +x "$INSTALL_BASE/scripts/manage.sh"

    # Create symlink for easy access
    ln -sf "$INSTALL_BASE/scripts/manage.sh" /usr/local/bin/jetup

    success "Management script created (use 'jetup' command)"
}

# ==============================================================================
# MAIN INSTALLATION
# ==============================================================================

# Setup PostgreSQL first
setup_postgresql

# Setup SSH (this will also set repository URLs)
setup_ssh || {
    error "SSH setup failed"
    exit 1
}

# Create directory structure
create_directory_structure

# Install Main Bot (using repository URL set by setup_ssh)
install_bot \
    "Jetup Bot" \
    "$BOT_REPO" \
    "$INSTALL_BASE/bot" \
    "jetup-bot" \
    "jetup.py"

# Install Helpbot (using repository URL set by setup_ssh)
install_bot \
    "Jetup Helpbot" \
    "$HELPBOT_REPO" \
    "$INSTALL_BASE/helpbot" \
    "jetup-helpbot" \
    "helpbot.py"

# Create management script
create_management_script

# ==============================================================================
# POST-INSTALLATION
# ==============================================================================

echo ""
echo -e "${GREEN}╔═══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║     Installation Completed Successfully!       ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════╝${NC}"
echo ""

info "Directory structure:"
echo "  $INSTALL_BASE/"
echo "  ├── bot/app/          # Main bot code"
echo "  ├── helpbot/app/      # Helpbot code"
echo "  └── shared/creds/     # PostgreSQL credentials"
echo ""

warn "Database credentials saved to:"
echo "  $INSTALL_BASE/shared/creds/postgres_credentials.txt"
echo ""

warn "Required configurations:"
echo ""
echo "1. Edit bot config:"
echo -e "   ${BLUE}nano $INSTALL_BASE/bot/app/.env${NC}"
echo "   - Add bot token"
echo "   - Add admin IDs"
echo ""
echo "2. Edit helpbot config:"
echo -e "   ${BLUE}nano $INSTALL_BASE/helpbot/app/.env${NC}"
echo "   - Add bot token"
echo "   - Add Google Sheet ID"
echo "   - Add helpbot group ID"
echo ""
echo "3. Add Google credentials:"
echo -e "   ${BLUE}cp /path/to/google_credentials.json $INSTALL_BASE/shared/creds/helpbot_key.json${NC}"
echo ""

log "Management commands:"
echo -e "  ${CYAN}jetup start${NC}      - Start all bots"
echo -e "  ${CYAN}jetup status${NC}     - Check status"
echo -e "  ${CYAN}jetup logs bot${NC}   - View bot logs"
echo -e "  ${CYAN}jetup backup${NC}     - Create backup"
echo -e "  ${CYAN}jetup db connect${NC} - Connect to database"
echo ""

info "Services created but not started. Start with: jetup start"
echo ""