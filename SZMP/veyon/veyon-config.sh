#!/bin/bash
sudo apt install veyon-configurator

veyon-cli config set Authentication/Method "KeyFileAuthentication"
sudo veyon-cli authkeys import diak/public diakok_public_key.pem

sudo systemctl enable veyon

sudo firewall-cmd --permanent --add-port=11100/tcp
sudo firewall-cmd --permanent --add-port=11101/tcp
sudo firewall-cmd --reload
