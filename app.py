from flask import Flask, render_template, request, jsonify, send_file
import pandas as pd
import requests
import io
import os

app = Flask(__name__)

# References: 
# Weather/Soil: Open-Meteo Archive (https://open-meteo.com/)
# LST/NDVI Proxy: NASA POWER (https://power.larc.nasa.gov/)

def get_centroid(coords):
    if isinstance(coords, dict): 
        return coords['lat'], coords['lng']
    lat = sum(p['lat'] for p in coords) / len(coords)
    lon = sum(p['lng'] for p in coords) / len(coords)
    return lat, lon

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_weather_data', methods=['POST'])
def get_weather_data():
    req_data = request.json
    lat, lon = get_centroid(req_data['coords'])
    start = req_data.get('start_date', '2023-01-01')
    end = req_data.get('end_date', '2023-12-31')

    # 1. Fetch Open-Meteo
    meteo_url = "https://archive-api.open-meteo.com/v1/archive"
    meteo_params = {
        "latitude": lat, "longitude": lon,
        "start_date": start, "end_date": end,
        "hourly": "temperature_2m,relative_humidity_2m,precipitation,et0_fao_evapotranspiration,wind_speed_10m,soil_moisture_0_to_7cm",
        "timezone": "auto"
    }
    
    try:
        m_res = requests.get(meteo_url, params=meteo_params).json()
        df_hourly = pd.DataFrame(m_res['hourly'])
        df_hourly['time'] = pd.to_datetime(df_hourly['time'])
        
        # 2. Fetch NASA Data (LST and Solar - NDVI Proxies)
        nasa_start = start.replace("-", "")
        nasa_end = end.replace("-", "")
        nasa_url = f"https://power.larc.nasa.gov/api/temporal/daily/point?parameters=TS,ALLSKY_SFC_SW_DWN&community=AG&longitude={lon}&latitude={lat}&start={nasa_start}&end={nasa_end}&format=JSON"
        n_res = requests.get(nasa_url).json()
        
        # Prepare NASA data for Excel merge
        nasa_dict = n_res['properties']['parameter']
        df_nasa = pd.DataFrame({
            'date': [pd.to_datetime(d) for d in nasa_dict['TS'].keys()],
            'Land_Surface_Temp_C': list(nasa_dict['TS'].values()),
            'Solar_Irradiance_kW_m2': list(nasa_dict['ALLSKY_SFC_SW_DWN'].values())
        })
        
        # Save both to local files for the Excel aggregator
        df_hourly.to_csv("latest_hourly.csv", index=False)
        df_nasa.to_csv("latest_nasa.csv", index=False)
        
        return jsonify({
            "status": "success",
            "data": m_res['hourly'],
            "nasa": nasa_dict
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/download')
def download():
    if os.path.exists("latest_hourly.csv") and os.path.exists("latest_nasa.csv"):
        df_h = pd.read_csv("latest_hourly.csv", parse_dates=['time'])
        df_n = pd.read_csv("latest_nasa.csv", parse_dates=['date'])
        
        # Temporal Resampling for Weather
        df_h.set_index('time', inplace=True)
        df_daily_weather = df_h.resample('D').mean()
        
        # Merge Weather and NASA Daily Data
        df_daily_combined = pd.merge(df_daily_weather, df_n, left_index=True, right_on='date', how='inner')
        
        # Create Monthly/Yearly from Combined
        df_daily_combined.set_index('date', inplace=True)
        df_monthly = df_daily_combined.resample('ME').mean()
        df_yearly = df_daily_combined.resample('YE').mean()

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_h.to_excel(writer, sheet_name='Hourly_Weather')
            df_daily_combined.to_excel(writer, sheet_name='Daily_Weather_and_NDVI_Proxy')
            df_monthly.to_excel(writer, sheet_name='Monthly_Summary')
            df_yearly.to_excel(writer, sheet_name='Yearly_Summary')
            
        output.seek(0)
        return send_file(output, as_attachment=True, download_name="Environmental_Data_Report.xlsx")
    return "No data", 404

if __name__ == '__main__':
    app.run(debug=True)