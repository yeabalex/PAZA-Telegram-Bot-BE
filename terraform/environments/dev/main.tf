# Latest Ubuntu 24.04 LTS AMI lookup
data "aws_ami" "ubuntu" {
  most_recent = true

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }

  owners = ["099720109477"] # Canonical
}

# --- SSH KEYPAIR GENERATION ---
resource "tls_private_key" "dev_key" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "aws_key_pair" "dev_key" {
  key_name   = "${var.project_name}-${var.environment}-key"
  public_key = tls_private_key.dev_key.public_key_openssh
}

resource "local_sensitive_file" "private_key" {
  content         = tls_private_key.dev_key.private_key_pem
  filename        = "${path.module}/dev_key.pem"
  file_permission = "0600"
}

# --- NETWORKING ---
resource "aws_vpc" "dev_vpc" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "${var.project_name}-${var.environment}-vpc"
  }
}

resource "aws_internet_gateway" "dev_igw" {
  vpc_id = aws_vpc.dev_vpc.id

  tags = {
    Name = "${var.project_name}-${var.environment}-igw"
  }
}

resource "aws_subnet" "dev_subnet" {
  vpc_id                  = aws_vpc.dev_vpc.id
  cidr_block              = "10.0.1.0/24"
  map_public_ip_on_launch = true

  tags = {
    Name = "${var.project_name}-${var.environment}-subnet"
  }
}

resource "aws_route_table" "dev_rt" {
  vpc_id = aws_vpc.dev_vpc.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.dev_igw.id
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-rt"
  }
}

resource "aws_route_table_association" "dev_rta" {
  subnet_id      = aws_subnet.dev_subnet.id
  route_table_id = aws_route_table.dev_rt.id
}

# --- SECURITY GROUP ---
resource "aws_security_group" "dev_sg" {
  name        = "${var.project_name}-${var.environment}-sg"
  description = "Security group for Dev Ubuntu server with Docker & HTTPS"
  vpc_id      = aws_vpc.dev_vpc.id

  # SSH
  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.allowed_ssh_cidr]
  }

  # HTTP
  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # HTTPS
  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # FastAPI Backend Direct Port
  ingress {
    description = "FastAPI Backend"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Outbound All
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-sg"
  }
}

# --- COMPUTE & USER_DATA ---
resource "aws_instance" "dev_server" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.dev_subnet.id
  vpc_security_group_ids = [aws_security_group.dev_sg.id]
  key_name               = aws_key_pair.dev_key.key_name

  root_block_device {
    volume_size           = 20
    volume_type           = "gp3"
    delete_on_termination = true
  }

  user_data_replace_on_change = true

  user_data = <<-EOF
#!/bin/bash
set -e

# 1. Immediately create custom deployment user (${var.ssh_user}) & configure SSH key
if ! id "${var.ssh_user}" &>/dev/null; then
    useradd -m -s /bin/bash ${var.ssh_user}
    mkdir -p /home/${var.ssh_user}/.ssh
    chmod 700 /home/${var.ssh_user}/.ssh
    cp /home/ubuntu/.ssh/authorized_keys /home/${var.ssh_user}/.ssh/authorized_keys
    chmod 600 /home/${var.ssh_user}/.ssh/authorized_keys
    chown -R ${var.ssh_user}:${var.ssh_user} /home/${var.ssh_user}/.ssh
    echo "${var.ssh_user} ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/99-${var.ssh_user}
fi

# 2. Update package list and install Docker & Caddy from official Ubuntu repos
apt-get update && apt-get install -y docker.io docker-compose-v2 caddy git curl

# 3. Enable & start Docker service and add users to docker group
systemctl enable --now docker
usermod -aG docker ${var.ssh_user}
usermod -aG docker ubuntu

# 4. Create application directory and set strict permissions (chmod 600 for .env)
APP_DIR="/home/${var.ssh_user}/app"
mkdir -p "$APP_DIR"
touch "$APP_DIR/.env"
chmod 600 "$APP_DIR/.env"
chmod 750 "$APP_DIR"
chown -R ${var.ssh_user}:${var.ssh_user} "$APP_DIR"

# 5. Retrieve Public IP from AWS EC2 Instance Metadata
TOKEN=$$(curl -s --max-time 5 -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600" || true)
if [ -n "$$TOKEN" ]; then
    PUBLIC_IP=$$(curl -s --max-time 5 -H "X-aws-ec2-metadata-token: $$TOKEN" http://169.254.169.254/latest/meta-data/public-ipv4)
else
    PUBLIC_IP=$$(curl -s --max-time 5 http://169.254.169.254/latest/meta-data/public-ipv4)
fi

# 6. Configure Caddy with nip.io HTTPS and block web access to .env
if [ -n "$$PUBLIC_IP" ]; then
    cat <<CADDY_CONF > /etc/caddy/Caddyfile
$${PUBLIC_IP}.nip.io {
    # Block web access to .env and hidden files
    respond /.env* "Access Denied" 403
    respond /.* "Access Denied" 403

    reverse_proxy localhost:8000
}
CADDY_CONF
    systemctl reload caddy || systemctl restart caddy
fi
EOF

  tags = {
    Name = "${var.project_name}-${var.environment}-server"
  }
}

# Elastic IP for persistent public IP address
resource "aws_eip" "dev_eip" {
  instance = aws_instance.dev_server.id
  domain   = "vpc"

  tags = {
    Name = "${var.project_name}-${var.environment}-eip"
  }
}
