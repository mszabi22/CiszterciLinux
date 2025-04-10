#!/bin/bash
#sudo apt install veyon-configurator
veyon-cli config set Authentication/Method "KeyFileAuthentication"
sudo veyon-cli authkeys import stuff/public stuff_public_key.pem
sudo veyon-cli service restart
sudo systemctl enable veyon
sudo firewall-cmd --permanent --add-port=11100/tcp
sudo firewall-cmd --permanent --add-port=11101/tcp
sudo firewall-cmd --reload



