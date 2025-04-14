firewall-cmd --set-default-zone=public
firewall-cmd --permanent --direct --add-rule ipv4 filter OUTPUT 0 -j ACCEPT
firewall-cmd --permanent --zone=public --add-service=ssh --add-service=http --add-service=https --add-service=mysql
firewall-cmd --permanent --zone=public --add-port=68/udp --add-port=67/udp 	#DHCP
firewall-cmd --permanent --zone=public --add-port=9100/tcp --add-port=5353/udp 	# printer
firewall-cmd --permanent --add-icmp-block-inversion
firewall-cmd --permanent --add-icmp-block=echo-reply
firewall-cmd --permanent --add-icmp-block=echo-request
firewall-cmd --permanent --add-port=11100/tcp
firewall-cmd --permanent --add-port=11101/tcp
firewall-cmd --reload


