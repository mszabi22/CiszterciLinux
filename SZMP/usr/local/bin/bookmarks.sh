#!/bin/bash
if [ `id \$USER | grep tanár | wc -l` = "1" ]; then
echo "smb://10.23.0.253/home/tanar/$USER u:\ 
smb://10.23.0.253/public/tanar t:\
" >> ~/.config/gtk-3.0/bookmarks
else
echo "smb://10.23.0.253/home/diak/$USER u:\ 
smb://10.23.0.253/public/diak s:\
" > ~/.config/gtk-3.0/bookmarks
fi