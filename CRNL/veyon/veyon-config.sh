#!/bin/bash
sudo veyon-cli authkeys import public stuff_public_key.pem
sudo veyon-cli service enable
sudo veyon-cli service restart