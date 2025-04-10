#!/bin/bash
sudo veyon-cli authkeys import diak/public diakok_public_key.pem
sudo veyon-cli service restart
sudo system enable veyon
sudo system start veyon
