import asyncio
import copy
import json
import os
import platform
import re
from typing import List, Dict, Union, Any

from app.attackpilot.downloaders.defs import Downloader
from app.attackpilot.entities.contract import ContractEntityForCompile
from app.attackpilot.settings import PROJECT_PATH, COMPILER_ROOT, NODE_PATH, SOLCJS_CODE, CACHE_DIR
from app.attackpilot.utils.solc import SourceMappingItem, Solc, SolcJS
from app.attackpilot.utils.tmpfile import wrap_run4tmpfile


class ContractCompileItem:
    def __init__(
            self, contract_address: str, bytecode: str,
            ast: Dict, source_mapping: List[SourceMappingItem],
            abi: List = None, contract_name: str = "",
            errors: List[Dict] = None,
            creation_bytecode: str = "",
            immutable_references: Dict = None,
            storage_layout: Dict = None
    ):
        self.contract_address = contract_address
        self.bytecode = bytecode  # Runtime Bytecode
        self.creation_bytecode = creation_bytecode  # Creation Bytecode
        self.ast = ast
        self.source_mapping = source_mapping
        self.abi = abi if abi is not None else []
        self.contract_name = contract_name
        self.errors = errors if errors is not None else []
        self.immutable_references = immutable_references if immutable_references is not None else {}
        self.storage_layout = storage_layout

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contract_address": self.contract_address,
            "bytecode": self.bytecode,
            "creation_bytecode": self.creation_bytecode,
            "ast": self.ast,
            "source_mapping": [item.to_dict() for item in self.source_mapping],
            "abi": self.abi,
            "errors": self.errors,
            "immutable_references": self.immutable_references,
            "storage_layout": self.storage_layout
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ContractCompileItem':
        raw_mappings = data.get("source_mapping", [])
        mapping_objs = [SourceMappingItem.from_dict(m) for m in raw_mappings]

        return cls(
            contract_address=data.get("contract_address", ""),
            bytecode=data.get("bytecode", ""),
            creation_bytecode=data.get("creation_bytecode", ""),
            ast=data.get("ast", {}),
            source_mapping=mapping_objs,
            abi=data.get("abi", []),
            errors=data.get("errors", []),
            immutable_references=data.get("immutable_references", {}),
            storage_layout=data.get("storage_layout")
        )

    def is_success(self) -> bool:
        """Helper to check if compilation yielded bytecode"""
        return bool(self.bytecode and len(self.bytecode) > 2)


class ContractDao:
    def __init__(self, downloader: Downloader):
        self.downloader = downloader

    async def get_contract_name(self, contract_address: str) -> str:
        # fetch contract name from source code
        result = await self.downloader.download(contract_address=contract_address)
        if isinstance(result, str) and len(result) < 5:
            file_path = os.path.join(CACHE_DIR, f"source/{contract_address}.json")
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except OSError:
                    pass
                result = await self.downloader.download(contract_address=contract_address)
        if isinstance(result, dict):
            contract_name = result.get("ContractName", "")
        else:
            print(f"[WARN] Expected dict but got {type(result)} for address {contract_address}")
            # 尝试转换为字符串并处理
            result_str = str(result)
            if result_str.startswith('{'):
                try:
                    result_dict = json.loads(result_str)
                    contract_name = result_dict.get("ContractName", "")
                except:
                    contract_name = ""
            else:
                contract_name = ""
        return contract_name

    async def get_source_code(self, contract_address: str) -> Dict[str, str]:
        """
        Return the contract source code, which is fetched from etherscan.

        :param contract_address: the address of specific contract
        :return: the mapping from filename to source code
        """
        # fetch source code and save to tmp file
        result = await self.downloader.download(contract_address=contract_address)
        if isinstance(result, str) and len(result) < 5:
            file_path = os.path.join(CACHE_DIR, f"source/{contract_address}.json")
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except OSError:
                    pass
                await asyncio.sleep(1)
                result = await self.downloader.download(contract_address=contract_address)
        try:
            source_code_raw = result['SourceCode']
            if source_code_raw.startswith('{') and source_code_raw.endswith('}'):
                if source_code_raw.startswith('{{'):
                    standard_json = json.loads(source_code_raw[1:-1])
                else:
                    standard_json = json.loads(source_code_raw)

                sources = standard_json.get('sources', {})
                return {fn: val['content'] for fn, val in sources.items() if 'content' in val}
            else:
                return {'': source_code_raw}
        except Exception:
            return {'': result.get('SourceCode', '')}

    async def get_compile_item_by_json(self, contract_address: str, result: Dict) -> ContractCompileItem:
        """
        Compile the contract source code, which is fetched from etherscan.

        :param result:
        :param contract_address: the address of specific contract
        :return: the compiled result
        """
        # fetch source code and save to tmp file
        if len(result) == 0 or result.get('SourceCode') in [None, '']:
            return ContractCompileItem(contract_address, '', dict(), list(),
                                       errors=[{"severity": "error", "message": "Empty Source Code"}])

        # use solc-bin to compile standard-json,
        # and use solc-js to compile one sol source code file
        product = None
        collected_errors = []

        try:
            raw_code = result['SourceCode']
            if raw_code.startswith('{'):
                if raw_code.startswith('{{'):
                    json.loads(raw_code[1:-1])
                else:
                    json.loads(raw_code)

                product = await self._get_compile_item_by_solc(
                    contract_address=contract_address,
                    result=result,
                )
        except Exception as e:
            collected_errors.append({"severity": "warning", "message": f"Solc-bin pre-check failed: {str(e)}"})

        if product is not None and product.is_success():
            return product

        if product is not None and product.errors:
            collected_errors.extend(product.errors)

        product_js = await self._get_compile_item_by_solcjs(
            contract_address=contract_address,
            result=result,
        )

        if product_js is not None and product_js.is_success():
            return product_js

        if product_js is not None and product_js.errors:
            collected_errors.extend(product_js.errors)

        return ContractCompileItem(contract_address, '', dict(), list(), errors=collected_errors)

    async def get_compile_item_from_entity(self, entity: ContractEntityForCompile) -> ContractCompileItem:
        sources_json = {path: {"content": code} for path, code in entity.sources.items()}

        settings = copy.deepcopy(entity.compiler_settings) if entity.compiler_settings else {}

        if not settings:
            settings = {
                "optimizer": {
                    "enabled": entity.optimizations_used,
                    "runs": entity.optimization_runs if entity.optimization_runs else 200
                }
            }
            if entity.evm_version and entity.evm_version.lower() != "default":
                settings["evmVersion"] = entity.evm_version

        settings["outputSelection"] = {
            "*": {
                "*": [
                    "evm.bytecode",
                    "evm.deployedBytecode",
                    "abi", "storageLayout"
                ],
                "": ["ast"]
            }
        }

        if entity.libraries:
            if "libraries" not in settings:
                settings["libraries"] = {}

            if isinstance(entity.libraries, dict):
                for file_name, libs in entity.libraries.items():
                    if file_name not in settings["libraries"]:
                        settings["libraries"][file_name] = {}
                    if isinstance(libs, dict):
                        settings["libraries"][file_name].update(libs)
                    else:
                        pass

        standard_json = {
            "language": "Solidity",
            "sources": sources_json,
            "settings": settings
        }

        mock_result = {
            "CompilerVersion": entity.compiler_version,
            "ContractName": entity.contract_name,
            "SourceCode": json.dumps(standard_json),
            "OptimizationUsed": "1" if entity.optimizations_used else "0",
            "Runs": str(entity.optimization_runs),
            "Library": ""
        }
        collected_errors = []

        product = await self._get_compile_item_by_solc(entity.address, mock_result)
        if product and product.is_success():
            return product
        if product and product.errors:
            collected_errors.extend(product.errors)

        product = await self._get_compile_item_by_solcjs(entity.address, mock_result)
        if product and product.is_success():
            return product
        if product and product.errors:
            collected_errors.extend(product.errors)

        return ContractCompileItem(entity.address, '', {}, [], abi=[], contract_name="", errors=collected_errors)

    async def resolve_source_function(self, entity: ContractEntityForCompile, calldata: str) -> Dict:
        """Resolve an external entry point using compiler AST evidence only.

        The returned compilation still requires historical-runtime validation by
        the caller. Offsets are UTF-8 byte offsets, not Python string indices.
        """
        if (not isinstance(calldata, str)
                or not re.fullmatch(r'0x[0-9a-fA-F]{8}(?:[0-9a-fA-F]{2})*', calldata)):
            raise ValueError('source_function_selector_unavailable')
        compiled = await self.get_compile_item_from_entity(entity)
        if not compiled.is_success() or any(e.get('severity') == 'error' for e in compiled.errors):
            raise ValueError('source_function_compilation_failed')
        return self._resolve_compiled_source_function(entity, calldata[:10].lower(), compiled)

    @staticmethod
    def _resolve_compiled_source_function(
            entity: ContractEntityForCompile, selector: str, compiled: ContractCompileItem,
    ) -> Dict:
        def source_range(node):
            raw = node.get('src') if isinstance(node, dict) else None
            if not isinstance(raw, str) or not re.fullmatch(r'\d+:\d+:\d+', raw):
                raise ValueError('source_function_location_unavailable')
            return tuple(int(value) for value in raw.split(':'))

        contracts, source_files = {}, {}
        if not isinstance(compiled.ast, dict) or not isinstance(entity.sources, dict):
            raise ValueError('source_function_ast_unavailable')
        for path, unit in compiled.ast.items():
            if path not in entity.sources or not isinstance(entity.sources[path], str):
                raise ValueError('source_function_source_unavailable')
            if not isinstance(unit, dict) or unit.get('nodeType') != 'SourceUnit':
                raise ValueError('source_function_ast_unavailable')
            _, _, file_id = source_range(unit)
            if file_id in source_files:
                raise ValueError('source_function_ambiguous_source')
            source_files[file_id] = path
            for node in unit.get('nodes', []):
                if node.get('nodeType') != 'ContractDefinition':
                    continue
                ident = node.get('id')
                if type(ident) is not int or ident in contracts:
                    raise ValueError('source_function_ambiguous_contract')
                contracts[ident] = node

        targets = [node for node in contracts.values() if node.get('name') == entity.contract_name]
        if len(targets) != 1 or targets[0].get('abstract') is True:
            raise ValueError('source_function_ambiguous_contract')
        target = targets[0]
        bases = target.get('linearizedBaseContracts')
        if (not isinstance(bases, list) or not bases or bases[0] != target['id']
                or any(type(ident) is not int or ident not in contracts for ident in bases)
                or len(set(bases)) != len(bases)):
            raise ValueError('source_function_inheritance_unavailable')

        # Solidity's C3 order starts with the most-derived implementation.
        # Do not walk into a base body when a derived public getter owns entry.
        for ident in bases:
            owner = contracts[ident]
            matches = [node for node in owner.get('nodes', [])
                       if isinstance(node.get('functionSelector'), str)
                       and node['functionSelector'].removeprefix('0x').lower() == selector[2:]
                       and node.get('visibility') in {'public', 'external'}]
            if len(matches) > 1:
                raise ValueError('source_function_ambiguous_selector')
            if not matches:
                continue
            function = matches[0]
            if function.get('nodeType') != 'FunctionDefinition' or function.get('kind') != 'function':
                raise ValueError('source_function_getter_unsupported')
            body = function.get('body')
            if body is None:
                continue
            if not isinstance(body, dict) or body.get('nodeType') != 'Block':
                raise ValueError('source_function_body_unavailable')
            start, length, file_id = source_range(function)
            body_start, body_length, body_file_id = source_range(body)
            path = source_files.get(file_id)
            if (path is None or length <= 0 or body_length <= 0 or body_file_id != file_id
                    or body_start < start or body_start + body_length > start + length):
                raise ValueError('source_function_location_unavailable')
            content = entity.sources[path].encode('utf-8')
            if start + length > len(content):
                raise ValueError('source_function_location_unavailable')
            try:
                prefix = content[:start].decode('utf-8')
                content[start:start + length].decode('utf-8')
            except UnicodeDecodeError:
                raise ValueError('source_function_location_unavailable') from None
            return {
                'filename': path, 'source_file_id': file_id,
                'code_start': start, 'code_length': length,
                'line_number': prefix.count('\n') + 1,
                'function_name': function.get('name'), 'selector': selector,
                'declaring_contract': owner.get('name'),
                'source_mapping': 'compiled_ast_function_selector', 'compiled': compiled,
            }
        raise ValueError('source_function_selector_unmapped')

    async def get_compile_item(self, contract_address: str) -> ContractCompileItem:
        """
        Compile the contract source code, which is fetched from etherscan.

        :param contract_address: the address of specific contract
        :return: the compiled result
        """
        result = await self.downloader.download(contract_address=contract_address)
        if isinstance(result, str) and len(result) < 5:
            return ContractCompileItem(contract_address, '', dict(), list(),
                                       errors=[{"severity": "error", "message": "Downloader returned invalid data"}])

        if result.get('SourceCode') in [None, '']:
            return ContractCompileItem(contract_address, '', dict(), list(),
                                       errors=[{"severity": "error", "message": "SourceCode field empty"}])

        return await self.get_compile_item_by_json(contract_address, result)

    def _parse_source_json(self, result: Dict) -> Union[Dict, None]:
        raw_code = result.get('SourceCode', '')
        clean_code = self._clean_source_code(raw_code)

        if not clean_code:
            return None

        parsed_json = None

        try:
            parsed_json = json.loads(clean_code)
        except json.JSONDecodeError:
            pass

        if parsed_json is None and clean_code.startswith('{') and clean_code.endswith('}'):
            try:
                parsed_json = json.loads(clean_code[1:-1])
            except json.JSONDecodeError:
                pass

        if parsed_json is None:
            return None

        if "language" in parsed_json:
            if "settings" not in parsed_json:
                parsed_json["settings"] = {}
            if "outputSelection" not in parsed_json["settings"]:
                parsed_json["settings"]["outputSelection"] = {}

            parsed_json["settings"]["outputSelection"]["*"] = {
                "*": ["evm.bytecode", "evm.deployedBytecode", "abi", "storageLayout"],
                "": ["ast"]
            }
            return parsed_json

        sources = {}
        for fname, content_node in parsed_json.items():
            if isinstance(content_node, dict) and "content" in content_node:
                sources[fname] = content_node
            else:
                sources[fname] = {"content": content_node}

        if not sources:
            return None

        return {
            "language": "Solidity",
            "sources": sources,
            "settings": {
                "optimizer": {
                    "enabled": result.get("OptimizationUsed", "0") == "1",
                    "runs": int(result.get("Runs", 200))
                },
                "outputSelection": {
                    "*": {
                        "*": ["evm.bytecode", "evm.deployedBytecode", "abi", "storageLayout"],
                        "": ["ast"]
                    }
                }
            }
        }

    def _resolve_solc_path(self, compiler_version: str) -> str:
        compiler_dir = str(COMPILER_ROOT)
        if not os.path.exists(compiler_dir):
            return ""

        system_name = platform.system().lower()
        if system_name == 'windows':
            prefix = "solc-windows-amd64-"
            suffix = ".exe"
        elif system_name == 'linux':
            prefix = "solc-linux-amd64-"
            suffix = ""
        else:
            prefix = "solc-macosx-amd64-" if system_name == 'darwin' else "solc-linux-amd64-"
            suffix = ""

        identity = self._compiler_identity(compiler_version)
        if identity is None:
            return ""
        target_base, target_commit = identity
        try:
            files = os.listdir(compiler_dir)
        except OSError:
            return ""

        pattern = re.compile(re.escape(prefix) + r'v(\d+\.\d+\.\d+)\+commit\.([0-9a-fA-F]{8})' + re.escape(suffix))
        for fname in sorted(files):
            match = pattern.fullmatch(fname)
            if (match and match[1] == target_base
                    and (target_commit is None or match[2].lower() == target_commit)
                    and os.path.isfile(os.path.join(compiler_dir, fname))):
                return os.path.join(compiler_dir, fname)
        return ""

    @staticmethod
    def _compiler_identity(version):
        if not isinstance(version, str):
            return None
        match = re.fullmatch(r'v?(\d+\.\d+\.\d+)(?:\+commit\.([0-9a-fA-F]{8}))?(?:\.(?:Linux|Windows|Darwin|Emscripten)\..+)?', version.strip())
        return (match[1], match[2].lower() if match[2] else None) if match else None

    async def _get_compile_item_by_solc(
            self, contract_address: str, result: Dict
    ) -> Union[ContractCompileItem, None]:
        """
        Compile the contract source code by `solc-bin`,
        and return the compiled item if available,
        otherwise return None.

        :param contract_address: the address of specific contract
        :param result: the result of the source code request
        :return: the compiled item or None
        """
        raw_version = result["CompilerVersion"]

        solc_path = self._resolve_solc_path(raw_version)

        if not solc_path or not os.path.exists(solc_path):
            return ContractCompileItem(contract_address, '', {}, [],
                                       errors=[
                                           {"severity": "error", "reason_code": "compiler_unavailable",
                                            "message": f"Matching native Solidity compiler is not installed: {raw_version}"}])

        contract_name = result["ContractName"]
        standard_json = self._parse_source_json(result)

        if standard_json:
            product = await wrap_run4tmpfile(
                data=json.dumps(standard_json),
                async_func=lambda p: Solc(solc_path).compile_json(p, contract_name),
            )
        else:
            libraries = None
            if result.get('Library') and result['Library'] != '':
                libraries = result['Library'].split(',')
                libraries = ['{}:0x{}'.format(*lib.split(':')) for lib in libraries]

            product = await wrap_run4tmpfile(
                data=self._clean_source_code(result['SourceCode']),
                async_func=lambda p: Solc(solc_path).compile_sol(
                    source_path=p,
                    contract_name=contract_name,
                    optimized=result["OptimizationUsed"] == '1',
                    optimize_runs=result["Runs"],
                    libraries=libraries,
                ),
            )

        # return the compilation result
        return ContractCompileItem(
            contract_address=contract_address,
            bytecode=product.bytecode,
            creation_bytecode=product.creation_bytecode,
            ast=product.ast,
            source_mapping=product.source_mapping,
            abi=product.abi,
            contract_name=contract_name,
            errors=getattr(product, 'errors', []),
            immutable_references=getattr(product, 'immutable_references', {}),
            storage_layout=getattr(product, 'storage_layout', None)
        ) if product is not None else None

    async def _get_compile_item_by_solcjs(
            self, contract_address: str, result: Dict
    ) -> Union[ContractCompileItem, None]:
        """
        Compile the contract source code by `solc-js`,
        and return the compiled item if available,
        otherwise return None.

        :param contract_address: the address of specific contract
        :param result: the result of the source code request
        :return: the compiled item or None
        """
        identity = self._compiler_identity(result["CompilerVersion"])
        if identity is None:
            return ContractCompileItem(contract_address, '', {}, [],
                                       errors=[{"severity": "error",
                                                "message": "Cannot parse compiler version for SolcJS"}])
        solc_version = 'v%s' % identity[0]
        if not os.path.isfile(os.path.join(PROJECT_PATH, 'node_modules', f'solc{solc_version}', 'package.json')):
            return ContractCompileItem(contract_address, '', {}, [], errors=[{
                "severity": "error", "reason_code": "compiler_unavailable",
                "message": f"Matching JavaScript Solidity compiler is not installed: {result['CompilerVersion']}",
            }])
        contract_name = result["ContractName"]
        _tmp_filename = "this_is_a_tmp_filename.sol"

        raw_source = result.get('SourceCode', '')
        clean_source = self._clean_source_code(raw_source)

        standard_json = self._parse_source_json(result)
        if standard_json is None:
            standard_json = {
                "language": "Solidity",
                "settings": {
                    "optimizer": {
                        "enabled": result["OptimizationUsed"] == '1',
                        "runs": int(result["Runs"]),
                    },
                },
                "sources": {
                    _tmp_filename: {
                        "content": clean_source,
                    }
                }
            }
            if result.get('Library') and result['Library'] != '':
                libraries = result['Library'].split(',')
                standard_json['settings']['libraries'] = {
                    lib.split(':')[0]: '0x%s' % lib.split(':')[1]
                    for lib in libraries
                }
        else:
            if "sources" in standard_json:
                for f_name, _data in standard_json["sources"].items():
                    if "content" in _data:
                        _data["content"] = self._clean_source_code(_data["content"])

        if 'settings' not in standard_json:
            standard_json['settings'] = {}
        standard_json['settings']['outputSelection'] = {
            "*": {
                "*": ["evm.bytecode", "evm.deployedBytecode", "abi", "storageLayout"],
                "": ["ast"],
            },
        }

        product = await wrap_run4tmpfile(
            data=("const expectedCompiler = " + json.dumps({"version": identity[0], "commit": identity[1]}) + ";\n"
                  + SOLCJS_CODE % (solc_version, json.dumps(standard_json))),
            async_func=lambda p: SolcJS(NODE_PATH).compile_json(p, contract_name)
        )
        if product is None:
            return ContractCompileItem(contract_address, '', {}, [],
                                       errors=[{"severity": "error", "message": "SolcJS wrapper returned None"}])

        new_ast = {}
        for k, v in product.ast.items():
            key_name = '' if k == _tmp_filename else k
            new_ast[key_name] = v

        for item in product.source_mapping:
            if item.filename == _tmp_filename:
                item.filename = ''

        return ContractCompileItem(
            contract_address=contract_address,
            bytecode=product.bytecode,
            creation_bytecode=product.creation_bytecode,
            ast=new_ast,
            source_mapping=product.source_mapping,
            abi=product.abi,
            contract_name=contract_name,
            errors=getattr(product, 'errors', []),
            immutable_references=getattr(product, 'immutable_references', {}),
            storage_layout=getattr(product, 'storage_layout', None)
        ) if product is not None else None

    async def is_contract(self, contract_address: str) -> bool:
        result = await self.downloader.download(contract_address=contract_address)
        return result != '0x'

    def _clean_source_code(self, source_code: str) -> str:
        # Whitespace and Unicode can be literal contents; every source byte also
        # contributes to metadata hashes and compiler UTF-8 source locations.
        # Preserve provider source exactly across native and JavaScript paths.
        return source_code


async def test():
    pass


