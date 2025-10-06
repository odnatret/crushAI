from ultralytics import YOLO
import os

def inspect_yolo_model(model_path):
    """Анализирует YOLO модель и возвращает информацию о классах"""
    
    if not os.path.exists(model_path):
        print(f"❌ Модель не найдена: {model_path}")
        return None
    
    try:
        # Загружаем модель
        model = YOLO(model_path)
        print(f"✅ Модель загружена: {model_path}")
        
        # Получаем имена классов
        if hasattr(model, 'names') and model.names:
            print(f"🎯 Количество классов: {len(model.names)}")
            print("📋 Список классов:")
            for class_id, class_name in model.names.items():
                print(f"   {class_id}: {class_name}")
            
            return model.names
        else:
            print("❌ Информация о классах не найдена в модели")
            return None
            
    except Exception as e:
        print(f"❌ Ошибка при загрузке модели: {e}")
        return None

# Использование
model_path = "pp1/best.pt"  # ваша модель повреждений
classes = inspect_yolo_model(model_path)

if classes:
    print(f"\n🎯 Модель может обнаружить {len(classes)} типов повреждений:")
    for class_id, class_name in classes.items():
        print(f"   - {class_name}")
