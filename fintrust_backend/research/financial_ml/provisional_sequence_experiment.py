"""Isolated model-family comparison on UNAPPROVED 12 FinMind annual candidates.

Explicit opt-in is required. This is retrospective next-year numeric prediction
for engineering research, NOT validated anomaly/fraud detection. No 1785,
no labels, no finance API, no production database.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
import warnings
from collections import defaultdict
from pathlib import Path

from .annual_panel_readiness import METRICS

FEATURES = tuple(METRICS)
MODELS = ('ridge', 'random_forest', 'mlp', 'gru', 'lstm', 'tcn', 'transformer')


def read_panel(source):
    import numpy as np
    path = Path(source)
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        needed = {'ticker', 'fiscal_year', 'training_admitted', 'original_asof_verified', *FEATURES}
        if missing := needed - set(reader.fieldnames or []):
            raise ValueError('expected_provisional_panel_schema:' + str(sorted(missing)))
        rows = list(reader)
    if not rows:
        raise ValueError('empty_panel')
    panel = defaultdict(dict)
    for row in rows:
        ticker = row['ticker'].strip()
        if ticker == '1785' or not (len(ticker) == 4 and ticker.isascii() and ticker.isdecimal()):
            raise ValueError('reserved_or_invalid_company')
        year = int(row['fiscal_year'])
        if year < 2013 or year > 2025:
            raise ValueError('unsupported_fiscal_year')
        if (row['training_admitted'].lower() != 'false' or
                row['original_asof_verified'].lower() != 'false'):
            raise ValueError('source_provenance_claim_conflicts_with_pilot')
        if year in panel[ticker]:
            raise ValueError('duplicate_company_year')
        numbers = []
        for key in FEATURES:
            amount = row[key].strip()
            if amount:
                try:
                    number = float(amount)
                except ValueError:
                    raise ValueError('nonnumeric_provisional_amount') from None
                if not math.isfinite(number):
                    raise ValueError('nonfinite_provisional_amount')
                numbers.append(number)
            else:
                numbers.append(float('nan'))
        panel[ticker][year] = np.asarray(numbers, dtype='float64')
    return panel, hashlib.sha256(path.read_bytes()).hexdigest()


def samples_for_next_year(panel, *, history=3):
    import numpy as np
    if history not in (3, 5):
        raise ValueError('history_must_be_3_or_5')
    entries = []
    for ticker, years in sorted(panel.items()):
        for target_year in sorted(years):
            lookback = tuple(range(target_year - history, target_year))
            if not all(yr in years for yr in lookback):
                continue
            x = np.stack([years[yr] for yr in lookback])
            y = years[target_year]
            if not np.isfinite(x).all() or not np.isfinite(y).all():
                continue  # no zero-filling missing original observations
            entries.append((ticker, target_year, x, y))
    return entries


def time_partition(entries):
    partitions = {'fit': [], 'validation': [], 'holdout': []}
    for sample in entries:
        year = sample[1]
        group = 'fit' if year <= 2020 else 'validation' if year <= 2022 else 'holdout'
        partitions[group].append(sample)
    for key, minimum in [('fit', 15), ('validation', 5), ('holdout', 5)]:
        if len(partitions[key]) < minimum:
            raise ValueError(f'insufficient_{key}_samples_{len(partitions[key])}_needs_{minimum}')
    if len({x[0] for x in partitions['fit']}) < 8:
        raise ValueError('insufficient_distinct_fit_companies')
    return partitions


def prepare_scaled(partitions):
    import numpy as np
    from sklearn.preprocessing import RobustScaler
    tr = partitions['fit']
    x = np.stack([e[2] for e in tr])
    y = np.stack([e[3] for e in tr])
    signed_log = lambda z: np.sign(z) * np.log1p(np.abs(z))
    scaler = RobustScaler(quantile_range=(25, 75))
    # ONLY fitting-period financial figures train the scaler, never validation or holdout.
    scaler.fit(np.concatenate([signed_log(x).reshape(-1, len(FEATURES)), signed_log(y)], axis=0))
    result = {}
    for key, items in partitions.items():
        raw_x = np.stack([e[2] for e in items])
        raw_y = np.stack([e[3] for e in items])
        transformed_x = scaler.transform(
            signed_log(raw_x).reshape(-1, len(FEATURES))).reshape(len(items), raw_x.shape[1], len(FEATURES))
        transformed_y = scaler.transform(signed_log(raw_y))
        if not (np.isfinite(transformed_x).all() and np.isfinite(transformed_y).all()):
            raise ValueError('nonfinite_scaled_amounts')
        result[key] = (transformed_x, transformed_y)
    return result, scaler


def build_neural(name, history, *, seed, hidden=24):
    import torch
    from torch import nn
    torch.manual_seed(seed)
    features = len(FEATURES)

    class Recurrent(nn.Module):
        def __init__(self, kind):
            super().__init__()
            self.cell = (nn.GRU if kind == 'gru' else nn.LSTM)(
                features, hidden, batch_first=True)
            self.head = nn.Sequential(nn.LayerNorm(hidden), nn.Linear(hidden, features))
        def forward(self, x):
            states, _ = self.cell(x)
            return self.head(states[:, -1, :])

    class TemporalConv(nn.Module):
        def __init__(self):
            super().__init__()
            self.layers = nn.Sequential(
                nn.Conv1d(features, hidden, 2, padding=1), nn.GELU(),
                nn.Conv1d(hidden, hidden, 2, padding=1), nn.GELU())
            self.head = nn.Linear(hidden, features)
        def forward(self, x):
            states = x.transpose(1, 2)
            for layer in self.layers:
                states = layer(states)
                if isinstance(layer, nn.Conv1d):
                    states = states[:, :, :-1]
            return self.head(states[:, :, -1])

    class Attention(nn.Module):
        def __init__(self):
            super().__init__()
            self.embed = nn.Linear(features, hidden)
            self.pos = nn.Parameter(torch.zeros(1, history, hidden))
            layer = nn.TransformerEncoderLayer(
                d_model=hidden, nhead=4, dim_feedforward=hidden * 2,
                dropout=0.1, batch_first=True)
            self.layers = nn.TransformerEncoder(
                layer, num_layers=1, enable_nested_tensor=False)
            self.head = nn.Linear(hidden, features)
        def forward(self, x):
            z = self.layers(self.embed(x) + self.pos)
            return self.head(z.mean(dim=1))

    if name in ('gru', 'lstm'):
        return Recurrent(name)
    if name == 'tcn':
        return TemporalConv()
    if name == 'transformer':
        return Attention()
    raise ValueError('invalid_neural_architecture')


def fit_model(name, scaled, *, epochs=40, seed=42, output=None):
    import numpy as np
    from sklearn.linear_model import Ridge
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.neural_network import MLPRegressor
    x, y = scaled['fit']
    vx, _ = scaled['validation']
    tx, _ = scaled['holdout']
    if name in ('ridge', 'random_forest', 'mlp'):
        x, vx, tx = (z.reshape(len(z), -1) for z in (x, vx, tx))
        if name == 'ridge':
            model = Ridge(alpha=10.0)
        elif name == 'random_forest':
            model = RandomForestRegressor(
                n_estimators=150, min_samples_leaf=3, n_jobs=1, random_state=seed)
        else:
            model = MLPRegressor(
                hidden_layer_sizes=(24, 12), alpha=2.0, max_iter=300,
                random_state=seed, early_stopping=False)
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore', category=UserWarning)
            model.fit(x, y)
        val_pred, test_pred = model.predict(vx), model.predict(tx)
        if output is not None:
            import joblib
            joblib.dump(model, Path(output) / f'{name}_experimental.joblib')
        return {'val_prediction': val_pred, 'test_prediction': test_pred,
                'trained_epochs': int(getattr(model, 'n_iter_', None) or 1),
                'backend': 'scikit-learn'}

    try:
        import torch
    except ImportError:
        raise RuntimeError('torch_missing_for_neural_architecture') from None
    torch.set_num_threads(min(torch.get_num_threads(), 4))
    model = build_neural(name, x.shape[1], seed=seed)
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.003, weight_decay=0.02)
    mse = torch.nn.MSELoss()
    train_x, train_y = (torch.tensor(z, dtype=torch.float32) for z in (x, y))
    val_x, val_y = (torch.tensor(z, dtype=torch.float32)
                    for z in scaled['validation'])
    test_x = torch.tensor(tx, dtype=torch.float32)
    rng = np.random.default_rng(seed)
    lowest, best_state, patience = float('inf'), None, 8
    for epoch in range(epochs):
        model.train()
        for ids in np.array_split(rng.permutation(len(train_x)),
                                  max(1, math.ceil(len(train_x) / 32))):
            loss = mse(model(train_x[ids]), train_y[ids])
            if not torch.isfinite(loss):
                raise ValueError('nonfinite_neural_loss')
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
        model.eval()
        with torch.no_grad():
            val_err = mse(model(val_x), val_y).item()
        if val_err < lowest - 1e-5:
            lowest = val_err
            best_state = {k: v.detach().clone()
                          for k, v in model.state_dict().items()}
            patience = 8
        else:
            patience -= 1
            if patience <= 0:
                break
    model.load_state_dict(best_state)
    model.eval()
    with torch.no_grad():
        val_pred, test_pred = model(val_x).numpy(), model(test_x).numpy()
    if output is not None:
        torch.save({'model': best_state, 'architecture': name,
                    'window': x.shape[1], 'candidate_data_only': True},
                   Path(output) / f'{name}_experimental.pt')
    return {'val_prediction': val_pred, 'test_prediction': test_pred,
            'trained_epochs': epoch + 1, 'backend': 'pytorch'}


def run(dataset, output, *, history=3, epochs=40, seed=42, models=MODELS,
        experimental_allow_unverified_data=False):
    import numpy as np
    if not experimental_allow_unverified_data:
        raise ValueError('requires_explicit_experimental_unverified_data_opt_in')
    if not 5 <= epochs <= 150:
        raise ValueError('epochs_must_be_between_5_and_150')
    if (not models or any(model not in MODELS for model in models)
            or len(set(models)) != len(models)):
        raise ValueError('invalid_model_list')
    if any(name in ('gru', 'lstm', 'tcn', 'transformer') for name in models):
        try:
            import torch
        except ImportError:
            raise RuntimeError(
                'PyTorch required for GRU/LSTM/TCN/Transformer; '
                'use --models ridge random_forest mlp for sklearn-only smoke.') from None

    panel, source_hash = read_panel(dataset)
    samples = samples_for_next_year(panel, history=history)
    partitions = time_partition(samples)
    scaled, scaler = prepare_scaled(partitions)
    folder = Path(output)
    folder.mkdir(parents=True, exist_ok=True)
    import joblib
    joblib.dump({'scaler': scaler, 'feature_names': FEATURES,
                 'candidate_data_only': True}, folder / 'candidate_scaler.joblib')

    records, scores = [], []
    for name in models:
        model = fit_model(name, scaled, epochs=epochs, seed=seed, output=folder)
        val_y, test_y = scaled['validation'][1], scaled['holdout'][1]
        val_pred, test_pred = model['val_prediction'], model['test_prediction']
        if not (np.isfinite(val_pred).all() and np.isfinite(test_pred).all()):
            raise ValueError('nonfinite_model_predictions')
        val_loss = float(np.mean((val_pred - val_y) ** 2))
        test_loss = float(np.mean((test_pred - test_y) ** 2))
        print(f'[Temporal pilot] {name} completed; validation_scaled_MSE={val_loss:.6f}; holdout_scaled_MSE={test_loss:.6f}', flush=True)
        records.append({
            'model': name, 'backend': model['backend'],
            'validation_scaled_mse': round(val_loss, 8),
            'holdout_scaled_mse': round(test_loss, 8),
            'trained_epochs': model['trained_epochs'],
            'target': 'next_year_financial_amounts_proxy'})
        anomaly_scores = np.mean(np.abs(test_pred - test_y), axis=1)
        for sample, score in zip(partitions['holdout'], anomaly_scores):
            scores.append({
                'model': name, 'ticker': sample[0],
                'target_year': sample[1],
                'proxy_prediction_residual': round(float(score), 7),
                'known_financial_misstatement_label': 'UNKNOWN'})
    # Model selection is validation-based, never chosen by the holdout scores.
    best = min(records, key=lambda x: x['validation_scaled_mse'])['model']
    def write_csv(name, rows):
        with (folder / name).open('w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    write_csv('architecture_comparison_experimental.csv', records)
    write_csv('holdout_proxy_residual_scores.csv', scores)
    report = {
        'status': 'RESEARCH_SMOKE_ONLY_UNVERIFIED_12_FINANCIAL_AMOUNTS',
        'source_sha256': source_hash, 'experiment_seed': seed,
        'history_years': history,
        'fit_targets': '2016-2020', 'validation_targets': '2021-2022',
        'untouched_holdout_targets': '2023-2025',
        'fit_windows': len(partitions['fit']),
        'validation_windows': len(partitions['validation']),
        'holdout_windows': len(partitions['holdout']),
        'fit_firms': len({x[0] for x in partitions['fit']}),
        'validation_firms': len({x[0] for x in partitions['validation']}),
        'holdout_firms': len({x[0] for x in partitions['holdout']}),
        'models_trained': list(models),
        'best_validation_proxy_model': best, 'comparison': records,
        'source_is_provisional': True,
        'labels_created': 0,
        'fraud_detection_accuracy_measurable': False,
        'source_publication_time_verified': False,
        'uses_Beneish_Dechow_15_variables': False,
        'reserved_1785_excluded': True,
        'production_db_writes': 0, 'network_requests': 0,
        'warning': (
            'Next-year annual amount prediction is a self-supervised engineering '
            'smoke test. Twelve candidate annual values are not approved literature '
            'features; losses and residual ranks are not fraud detection. '
            'Same firms may appear in distinct time periods; issuer-disjoint '
            'validation and filing-publication time audits remain necessary.')
    }
    (folder / 'experiment_report.json').write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return report


def main(argv=None):
    p = argparse.ArgumentParser(
        description='Experimental next-year cross-architecture learning; not fraud ML')
    p.add_argument('--dataset', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--history', type=int, choices=(3, 5), default=3)
    p.add_argument('--epochs', type=int, default=40)
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--models', nargs='+', choices=MODELS, default=list(MODELS))
    p.add_argument('--experimental-allow-unverified-data', action='store_true', required=True)
    args = p.parse_args(argv)
    print(json.dumps(run(
        args.dataset, args.output, history=args.history, epochs=args.epochs,
        seed=args.seed, models=tuple(args.models),
        experimental_allow_unverified_data=args.experimental_allow_unverified_data),
        indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
