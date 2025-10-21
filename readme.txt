cat cewlpp_netflix.com_1760949359_endpoints.txt | grep -o "'/[^']*'" | sed "s/'//g" > temp_endpoints.txt

this command us use for endpoints in one line command 
