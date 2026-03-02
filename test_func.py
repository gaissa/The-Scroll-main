from app import app, init_supabase

with app.app_context():
    init_supabase()
    from utils.stats import get_stats_data
    try:
        data = get_stats_data()
        print("KEYS:", data.keys())
        if 'error' in data:
            print("ERROR IN DATA:", data['error'])
    except Exception as e:
        import traceback
        traceback.print_exc()
