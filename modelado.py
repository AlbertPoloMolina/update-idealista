from __future__ import annotations

from pathlib import Path
from datetime import datetime
import io
import ssl
import urllib.request
import json

import certifi
import numpy as np
import pandas as pd

from sklearn.model_selection import train_test_split, KFold, cross_val_score, GridSearchCV
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.compose import ColumnTransformer, TransformedTargetRegressor
from sklearn.pipeline import Pipeline
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import r2_score, mean_squared_error

import joblib


# -------------------------------------------------------------------------
# Configuración general
# -------------------------------------------------------------------------

HIST_URL = (
    "https://raw.githubusercontent.com/AlbertPoloMolina/update-idealista/"
    "refs/heads/main/historial_idealista.csv"
)

RANDOM_STATE = 1802
TEST_SIZE = 0.2
N_SPLITS_CV = 5


# -------------------------------------------------------------------------
# Carga y preparación de datos
# -------------------------------------------------------------------------

def cargar_historial(url: str = HIST_URL) -> pd.DataFrame:
    """Descarga el histórico de Idealista desde GitHub y lo carga en un DataFrame."""
    ctx = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(url, context=ctx) as resp:
        csv_text = resp.read().decode("utf-8")
    hist = pd.read_csv(io.StringIO(csv_text))
    return hist


def preparar_dataset(hist: pd.DataFrame) -> pd.DataFrame:
    """
    Limpieza mínima del dataset para modelado.

    - Define la columna objetivo `PrecioFinal` si no existe (usa `price`).
    - Elimina filas sin precio final.
    """
    df = hist.copy()

    if "PrecioFinal" not in df.columns:
        if "price" not in df.columns:
            raise KeyError("El dataset no contiene la columna 'price' ni 'PrecioFinal'.")
        df["PrecioFinal"] = df["price"]

    df = df.dropna(subset=["PrecioFinal"])

    return df


def _coerce_binary_value(value) -> int:
    """Convierte distintos formatos a 0/1."""
    if pd.isna(value):
        return 0
    if isinstance(value, (bool, np.bool_)):
        return int(value)
    if isinstance(value, (int, np.integer)):
        return int(bool(value))

    if isinstance(value, str):
        val = value.strip()
        if not val:
            return 0
        lower = val.lower()
        if lower in {"true", "1", "yes", "y", "si", "sí"}:
            return 1
        if lower in {"false", "0", "no", "n"}:
            return 0
        if val.startswith("{") and val.endswith("}"):
            try:
                val_json = json.loads(val.replace("'", '"'))
                if isinstance(val_json, dict):
                    for key in ("hasParkingSpace", "parkingSpace", "value"):
                        if key in val_json:
                            return int(bool(val_json[key]))
            except Exception:
                pass
        if "true" in lower:
            return 1
    return 0


def configurar_preprocesamiento(df: pd.DataFrame):
    """
    Construye X, y y el preprocesador (ColumnTransformer).

    Se utilizan columnas robustas que suelen estar presentes en el histórico.
    Si alguna falta, simplemente no se usa.
    """
    y = df["PrecioFinal"].astype(float)

    features_num = ["rooms", "bathrooms", "size", "numPhotos"]
    features_bin = ["hasLift", "newDevelopment", "hasVideo", "parkingSpace"]
    features_cat = ["propertyType", "Distrito_censal", "floor", "status"]

    columnas_ordenadas = [c for c in features_num + features_bin + features_cat if c in df.columns]
    if not columnas_ordenadas:
        raise ValueError("No hay columnas de entrada disponibles para el modelo.")

    X = df[columnas_ordenadas].copy()

    num_cols = [c for c in features_num if c in X.columns]
    bin_cols = [c for c in features_bin if c in X.columns]
    cat_cols = [c for c in features_cat if c in X.columns]

    # Conversión de tipos
    for col in bin_cols:
        X[col] = X[col].apply(_coerce_binary_value).astype("Int64")

    for col in cat_cols:
        X[col] = X[col].astype("string").fillna("NA")

    preprocessor = ColumnTransformer(
        transformers=[
            ("num", StandardScaler(), num_cols),
            ("bin", "passthrough", bin_cols),
            ("cat", OneHotEncoder(handle_unknown="ignore"), cat_cols),
        ],
        remainder="drop",
    )

    return X, y, preprocessor


# -------------------------------------------------------------------------
# Modelado y validación
# -------------------------------------------------------------------------

def construir_modelo(preprocessor: ColumnTransformer) -> Pipeline:
    """Crea el pipeline de modelado con Random Forest y transformación logarítmica del target."""
    regressor = RandomForestRegressor(
        n_estimators=400,
        max_depth=None,
        min_samples_split=5,
        min_samples_leaf=2,
        random_state=RANDOM_STATE,
        n_jobs=-1,
    )

    model = Pipeline(
        steps=[
            ("preprocessor", preprocessor),
            ("regressor", TransformedTargetRegressor(
                regressor=regressor,
                func=np.log1p,
                inverse_func=np.expm1,
            )),
        ]
    )
    return model


def optimizar_modelo(preprocessor: ColumnTransformer, X_train: pd.DataFrame, y_train: pd.Series):
    """
    Realiza una búsqueda de hiperparámetros (GridSearchCV) para el Random Forest.
    """
    pipeline = construir_modelo(preprocessor)
    param_grid = {
        "regressor__regressor__n_estimators": [300, 400, 500],
        "regressor__regressor__max_depth": [None, 12, 16],
        "regressor__regressor__min_samples_split": [2, 5, 10],
        "regressor__regressor__min_samples_leaf": [1, 2, 4],
        "regressor__regressor__max_features": ["sqrt", "log2", 0.7],
    }
    search = GridSearchCV(
        estimator=pipeline,
        param_grid=param_grid,
        scoring="neg_root_mean_squared_error",
        cv=3,
        n_jobs=-1,
        refit=True,
    )
    search.fit(X_train, y_train)
    return search.best_estimator_, search.best_params_


def evaluar_modelo(model: Pipeline, X_test: pd.DataFrame, y_test: pd.Series) -> dict:
    """Devuelve métricas en test sin imprimir nada."""
    y_pred = model.predict(X_test)
    r2 = r2_score(y_test, y_pred)
    rmse = float(np.sqrt(mean_squared_error(y_test, y_pred)))
    return {"r2": float(r2), "rmse": rmse}


def validacion_cruzada(model: Pipeline, X: pd.DataFrame, y: pd.Series) -> dict:
    """Calcula validación cruzada (R² medio y desviación estándar)."""
    kfold = KFold(n_splits=N_SPLITS_CV, shuffle=True, random_state=RANDOM_STATE)
    scores_r2 = cross_val_score(model, X, y, cv=kfold, scoring="r2", n_jobs=-1)
    return {
        "cv_r2_mean": float(scores_r2.mean()),
        "cv_r2_std": float(scores_r2.std()),
    }


# -------------------------------------------------------------------------
# Gestión de modelos en disco
# -------------------------------------------------------------------------

def mover_modelos_anteriores(model_dir: Path) -> None:
    """Mueve cualquier modelo existente en `model_dir` a `model_dir / 'anteriores'`."""
    model_dir.mkdir(parents=True, exist_ok=True)
    prev_dir = model_dir / "anteriores"
    prev_dir.mkdir(parents=True, exist_ok=True)

    for path in model_dir.glob("*.joblib"):
        if path.is_file():
            destino = prev_dir / path.name
            # Si ya existe un archivo con el mismo nombre en anteriores, lo sobreescribimos
            if destino.exists():
                destino.unlink()
            path.rename(destino)


def guardar_modelo(model: Pipeline, metrics: dict, model_dir: Path) -> Path:
    """
    Guarda el modelo y las métricas en un archivo .joblib fechado.

    El archivo contiene un diccionario con:
    - 'model': el Pipeline entrenado
    - 'metrics': diccionario con métricas de test y CV
    """
    model_dir.mkdir(parents=True, exist_ok=True)
    mover_modelos_anteriores(model_dir)

    fecha = datetime.now().strftime("%Y%m%d")
    model_path = model_dir / f"modelo_precios_{fecha}.joblib"

    joblib.dump({"model": model, "metrics": metrics}, model_path)
    return model_path


# -------------------------------------------------------------------------
# Flujo principal
# -------------------------------------------------------------------------

def main() -> None:
    # 1) Carga y preparación de datos
    hist = cargar_historial()
    df = preparar_dataset(hist)
    X, y, preprocessor = configurar_preprocesamiento(df)

    # 2) Split entrenamiento / test
    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=TEST_SIZE,
        random_state=RANDOM_STATE,
    )

    # 3) Optimización y entrenamiento del modelo
    model, best_params = optimizar_modelo(preprocessor, X_train, y_train)

    # 4) Evaluación (test + validación cruzada)
    metrics_test = evaluar_modelo(model, X_test, y_test)
    metrics_cv = validacion_cruzada(model, X_train, y_train)
    metrics = {"test": metrics_test, "cv": metrics_cv, "best_params": best_params}

    # 5) Guardar modelo
    model_dir = Path("./modelado")
    guardar_modelo(model, metrics, model_dir)


if __name__ == "__main__":
    main()
