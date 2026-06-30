# Scraped from https://finder.nyc.gov/coolingcenters/locations?mView=map
wget "https://services6.arcgis.com/yG5s3afENB5iO9fj/arcgis/rest/services/Cool_Options/FeatureServer/0/query?f=geojson&resultRecordCount=20000&where=(Location_type%20%3D%20%27Indoor%27)%20OR%20(Location_type%20%3D%20%27Outdoor%27)&outFields=*&spatialRel=esriSpatialRelIntersects" -O data/cooling_centers.geojson
