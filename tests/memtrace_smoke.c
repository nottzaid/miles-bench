/* Exercises every memtrace event through the real d3d12.dll loading path:
 * committed texture + upload buffer, heap + placed buffer, SetName, release. */
#define COBJMACROS
#define INITGUID
#include <windows.h>
#include <d3d12.h>
#include <stdio.h>

__declspec(noinline) ID3D12Resource *smoke_committed_texture(ID3D12Device *device)
{
    D3D12_HEAP_PROPERTIES props = { D3D12_HEAP_TYPE_DEFAULT };
    D3D12_RESOURCE_DESC desc = { D3D12_RESOURCE_DIMENSION_TEXTURE2D, 0, 1024, 1024, 1, 1,
            DXGI_FORMAT_R8G8B8A8_UNORM, { 1, 0 }, D3D12_TEXTURE_LAYOUT_UNKNOWN, D3D12_RESOURCE_FLAG_NONE };
    ID3D12Resource *res = NULL;
    HRESULT hr = ID3D12Device_CreateCommittedResource(device, &props, D3D12_HEAP_FLAG_NONE, &desc,
            D3D12_RESOURCE_STATE_COMMON, NULL, &IID_ID3D12Resource, (void **)&res);
    printf("committed texture: %#lx\n", hr);
    if (res) ID3D12Resource_SetName(res, L"smoke_texture");
    return res;
}

__declspec(noinline) ID3D12Resource *smoke_upload_buffer(ID3D12Device *device)
{
    D3D12_HEAP_PROPERTIES props = { D3D12_HEAP_TYPE_UPLOAD };
    D3D12_RESOURCE_DESC desc = { D3D12_RESOURCE_DIMENSION_BUFFER, 0, 64 << 20, 1, 1, 1,
            DXGI_FORMAT_UNKNOWN, { 1, 0 }, D3D12_TEXTURE_LAYOUT_ROW_MAJOR, D3D12_RESOURCE_FLAG_NONE };
    ID3D12Resource *res = NULL;
    HRESULT hr = ID3D12Device_CreateCommittedResource(device, &props, D3D12_HEAP_FLAG_NONE, &desc,
            D3D12_RESOURCE_STATE_GENERIC_READ, NULL, &IID_ID3D12Resource, (void **)&res);
    printf("upload buffer: %#lx\n", hr);
    if (res) ID3D12Resource_SetName(res, L"smoke_upload");
    return res;
}

__declspec(noinline) ID3D12Resource *smoke_placed(ID3D12Device *device, ID3D12Heap **heap)
{
    D3D12_HEAP_DESC heap_desc = { 16 << 20, { D3D12_HEAP_TYPE_DEFAULT }, 0, D3D12_HEAP_FLAG_ALLOW_ONLY_BUFFERS };
    D3D12_RESOURCE_DESC desc = { D3D12_RESOURCE_DIMENSION_BUFFER, 0, 4 << 20, 1, 1, 1,
            DXGI_FORMAT_UNKNOWN, { 1, 0 }, D3D12_TEXTURE_LAYOUT_ROW_MAJOR, D3D12_RESOURCE_FLAG_NONE };
    ID3D12Resource *res = NULL;
    HRESULT hr = ID3D12Device_CreateHeap(device, &heap_desc, &IID_ID3D12Heap, (void **)heap);
    printf("heap: %#lx\n", hr);
    if (FAILED(hr)) return NULL;
    ID3D12Heap_SetName(*heap, L"smoke_heap");
    hr = ID3D12Device_CreatePlacedResource(device, *heap, 1 << 20, &desc, D3D12_RESOURCE_STATE_COMMON,
            NULL, &IID_ID3D12Resource, (void **)&res);
    printf("placed buffer: %#lx\n", hr);
    if (res) ID3D12Resource_SetName(res, L"smoke_placed");
    return res;
}

int main(void)
{
    ID3D12Resource *tex, *upload, *placed;
    ID3D12Device *device = NULL;
    ID3D12Heap *heap = NULL;
    HRESULT hr;

    hr = D3D12CreateDevice(NULL, D3D_FEATURE_LEVEL_11_0, &IID_ID3D12Device, (void **)&device);
    printf("device: %#lx\n", hr);
    if (FAILED(hr)) return 1;

    tex = smoke_committed_texture(device);
    upload = smoke_upload_buffer(device);
    placed = smoke_placed(device, &heap);
    printf("rva committed_texture=%#llx upload_buffer=%#llx placed=%#llx\n",
            (unsigned long long)((char *)smoke_committed_texture - (char *)GetModuleHandleA(NULL)),
            (unsigned long long)((char *)smoke_upload_buffer - (char *)GetModuleHandleA(NULL)),
            (unsigned long long)((char *)smoke_placed - (char *)GetModuleHandleA(NULL)));

    if (placed) ID3D12Resource_Release(placed);
    if (heap) ID3D12Heap_Release(heap);
    if (upload) ID3D12Resource_Release(upload);
    if (tex) ID3D12Resource_Release(tex);
    ID3D12Device_Release(device);
    return 0;
}
