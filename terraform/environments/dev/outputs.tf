output "ssh_user" {
  description = "SSH Username for deployment access"
  value       = var.ssh_user
}

output "public_ip" {
  description = "Elastic Public IP of the Dev EC2 instance"
  value       = aws_eip.dev_eip.public_ip
}

output "domain_name" {
  description = "nip.io domain configured with SSL/HTTPS"
  value       = "${aws_eip.dev_eip.public_ip}.nip.io"
}

output "https_url" {
  description = "HTTPS URL targeting the backend application"
  value       = "https://${aws_eip.dev_eip.public_ip}.nip.io"
}

output "ssh_command" {
  description = "Command to SSH into the EC2 server"
  value       = "ssh -i dev_key.pem ${var.ssh_user}@${aws_eip.dev_eip.public_ip}"
}

output "ssh_private_key_pem" {
  description = "Private key PEM content for SSH access"
  value       = tls_private_key.dev_key.private_key_pem
  sensitive   = true
}

output "key_file_path" {
  description = "Local relative file path where private key is saved"
  value       = local_sensitive_file.private_key.filename
}
